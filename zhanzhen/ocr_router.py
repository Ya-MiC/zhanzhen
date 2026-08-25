"""OCR 三级降级链路由器 —— docs/OCR_STRATEGY.md §2 的服务端软件化。

按输入类型自动选路，全部不可用时给出明确的 NEEDS_SERVER（绝不静默编数据）：

  .pdf             → TextLayerPDFProvider（文本层直取，零成本，已有）
  .txt             → StubProvider（确定性文本桩，兼容 demo/测试管线）
  .jpg/.jpeg/.png  → ① 系统级 OCR：命令行 tesseract 存在即用（lang=chi_sim）
                     ② PaddleOCR：python 包 paddleocr 可导入则真调
                     ③ 均不可用 → NeedsServerError("NEEDS_SERVER"，
                        提示安装本地引擎或升级服务端 OCR 专业版）

诚实原则（ENGINEERING_SPEC §5）：探测不到引擎就明说；tesseract / paddleocr
均为懒加载探测，本模块只依赖标准库。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .ocr import (
    FileRef,
    OCRJobOptions,
    OCRProvider,
    OCRResult,
    StubProvider,
    TextLayerPDFProvider,
)

__all__ = [
    "NeedsServerError", "TesseractProvider", "PaddleProvider",
    "OcrRouter", "probe_tesseract", "probe_paddleocr",
]

IMAGE_EXTS = (".jpg", ".jpeg", ".png")

# tesseract 语言包名与通用 lang 代码的映射（OCRJobOptions.lang → CLI -l 参数）
_TESS_LANG = {"ch": "chi_sim", "zh": "chi_sim", "chi_sim": "chi_sim", "en": "eng"}


class NeedsServerError(RuntimeError):
    """三级降级链全部不可用：需安装本地引擎或使用服务端 OCR（专业版）。

    继承 RuntimeError 以便 service.run_ocr 的既有异常通道也能兜底处理。
    """

    code = "NEEDS_SERVER"


def probe_tesseract() -> Optional[str]:
    """①系统级 OCR 探测：PATH 上存在 tesseract 可执行文件则返回其路径。"""
    return shutil.which("tesseract")


def probe_paddleocr() -> bool:
    """②PaddleOCR 探测：python 包可导入即为 True（仅 import，不初始化模型）。"""
    try:
        import paddleocr  # noqa: F401
        return True
    except Exception:          # ImportError 之外，paddle 还可能抛原生初始化错误
        return False


def _write_temp_image(content_bytes: bytes, filename: str) -> str:
    """把图片字节落到临时文件（引擎都需要真实文件路径），返回路径。"""
    suffix = os.path.splitext(filename or "")[1].lower() or ".png"
    tf = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tf.write(content_bytes)
        return tf.name
    finally:
        tf.close()


class TesseractProvider:
    """①系统级 OCR：懒加载 subprocess 调 tesseract（默认 chi_sim）。

    输出文本交给 TextLayerPDFProvider._from_text 既有抽取管线，
    归一化为 VoucherJSON v1——不引入第二套字段解析逻辑。
    """

    name = "tesseract-cli"

    def __init__(self, lang: str = "chi_sim", binary: Optional[str] = None) -> None:
        self.lang = lang
        self._binary = binary          # 懒解析：留到 process 时再 which()

    @staticmethod
    def available() -> bool:
        return probe_tesseract() is not None

    def _resolve_binary(self) -> Optional[str]:
        if self._binary is None:
            self._binary = probe_tesseract()
        return self._binary

    def process(self, file_ref: FileRef, options: OCRJobOptions) -> OCRResult:
        binary = self._resolve_binary()
        if not binary:
            raise NeedsServerError(
                "系统 OCR 不可用：PATH 上未找到 tesseract。请安装 "
                "tesseract-ocr 与简体中文语言包（tesseract-ocr-chi-sim），"
                "或 pip install 'zhanzhen[ocr]' 启用 PaddleOCR。")
        lang = _TESS_LANG.get(options.lang or self.lang, self.lang)
        tmp_path = _write_temp_image(file_ref.content_bytes, file_ref.filename)
        try:
            proc = subprocess.run(
                [binary, tmp_path, "stdout", "-l", lang],
                capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"tesseract 识别超时(>120s): {file_ref.filename}") from e
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace")[:200]
            raise RuntimeError(f"tesseract 退出码 {proc.returncode}: {stderr}")
        text = proc.stdout.decode("utf-8", "replace")
        result = TextLayerPDFProvider()._from_text(text, file_ref, options)
        result.engine_name = self.name
        result.model_version = f"tesseract-{lang}"
        result.raw_engine["text_chars"] = len(text)
        result.raw_engine["tesseract_lang"] = lang
        return result


class PaddleProvider:
    """②PaddleOCR 骨架：包可导入则真调 PP-OCR，失败给可读错误。

    引擎对象懒初始化（首次 process 才加载模型，导入探测阶段零开销）；
    结果解析兼容 paddleocr 2.x 的 [[box,(text,score)], ...] 结构。
    """

    name = "paddleocr"

    def __init__(self, lang: str = "ch") -> None:
        self.lang = lang
        self._engine = None

    @staticmethod
    def available() -> bool:
        return probe_paddleocr()

    def _get_engine(self):
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR
            except Exception as e:   # 导入成功过但加载期损坏/缺依赖
                raise RuntimeError(
                    "paddleocr 加载失败，请检查安装完整性："
                    "pip install 'zhanzhen[ocr]'（paddleocr+paddlepaddle）") from e
            # show_log 已在部分版本移除，逐个尝试以兼容 2.6/2.7+
            for kwargs in ({"show_log": False}, {},
                           {"use_angle_cls": True, "lang": self.lang, "show_log": False},
                           {"use_angle_cls": True, "lang": self.lang}):
                try:
                    self._engine = PaddleOCR(lang=self.lang, **{
                        k: v for k, v in kwargs.items() if k != "lang"})
                    break
                except TypeError:
                    continue
            if self._engine is None:
                raise RuntimeError("paddleocr 初始化失败：无法匹配已安装版本的构造参数")
        return self._engine

    @staticmethod
    def _extract_text(raw) -> str:
        lines = []
        for page in raw or []:
            if not page:
                continue
            for item in page:
                try:
                    txt = item[1][0]
                except (TypeError, IndexError):
                    continue
                if txt:
                    lines.append(str(txt))
        return "\n".join(lines)

    def process(self, file_ref: FileRef, options: OCRJobOptions) -> OCRResult:
        engine = self._get_engine()
        tmp_path = _write_temp_image(file_ref.content_bytes, file_ref.filename)
        try:
            for call in (
                lambda: engine.ocr(tmp_path, cls=True),
                lambda: engine.ocr(tmp_path),           # 新版移除了 cls 形参
                lambda: engine.predict(tmp_path),
            ):
                try:
                    raw = call()
                    break
                except TypeError:
                    continue
            else:
                raise RuntimeError("paddleocr 调用失败：无可用接口（ocr/predict）")
        except NeedsServerError:
            raise
        except RuntimeError:
            raise
        except Exception as e:                            # paddle 原生异常统一转可读错误
            raise RuntimeError(f"PaddleOCR 推理失败: {e}") from e
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        text = self._extract_text(raw)
        result = TextLayerPDFProvider()._from_text(text, file_ref, options)
        result.engine_name = self.name
        result.model_version = "pp-ocrv4"
        result.raw_engine["text_chars"] = len(text)
        return result


class OcrRouter:
    """三级降级链调度器：按文件类型自动选路（docs/OCR_STRATEGY.md §2）。

    route() 返回 (provider, chain)；chain 记录命中引擎名，便于响应里
    回显 fallbackChain。图片类按 ①tesseract ②paddleocr ③NEEDS_SERVER 顺序探测。
    探针函数可在构造时注入（测试替身），默认用模块级真实探测。
    """

    def __init__(self,
                 tesseract_probe=probe_tesseract,
                 paddle_probe=probe_paddleocr) -> None:
        self._tesseract_probe = tesseract_probe
        self._paddle_probe = paddle_probe

    def image_chain(self) -> list:
        """当前环境对图片可用的引擎序列（按降级优先序，仅供诊断/测试）。"""
        chain = []
        if self._tesseract_probe():
            chain.append("tesseract-cli")
        if self._paddle_probe():
            chain.append("paddleocr")
        return chain

    def route(self, filename: str):
        """按扩展名选 provider；返回 (provider, chain)。

        - .pdf → TextLayerPDFProvider（文本层直取）
        - .txt → StubProvider（确定性桩，兼容既有 demo/测试管线）
        - 图片 → 三级降级链；全不可用抛 NeedsServerError(code=NEEDS_SERVER)
        """
        lower = (filename or "").lower()
        if lower.endswith(".pdf"):
            return TextLayerPDFProvider(), ["pdf-textlayer"]
        if lower.endswith(".txt"):
            return StubProvider(), ["stub"]
        if lower.endswith(IMAGE_EXTS):
            chain = []
            if self._tesseract_probe():
                chain.append(TesseractProvider.name)
                return TesseractProvider(lang="chi_sim"), chain
            if self._paddle_probe():
                chain.append(PaddleProvider.name)
                return PaddleProvider(), chain
            chain.append(NeedsServerError.code)
            raise NeedsServerError(
                "图片识别的三级降级链在本机均不可用："
                "① 未找到命令行 tesseract（系统级 OCR）；"
                "② python 包 paddleocr 未安装（端侧 PP-OCR）。"
                "请任选其一安装：apt install tesseract-ocr tesseract-ocr-chi-sim "
                "或 pip install 'zhanzhen[ocr]'；"
                "或升级专业版改用服务端 OCR。")
        raise ValueError(
            f"暂不支持的文件类型: {filename}（支持 pdf/txt/jpg/jpeg/png）")

    def route_or_raise(self, filename: str) -> OCRProvider:
        return self.route(filename)[0]
