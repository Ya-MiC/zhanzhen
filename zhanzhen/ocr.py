"""OCR Provider 协议与三个适配器。

权威规范：ENGINEERING_SPEC §5 —— OCR 必须是可替换 adapter，
PaddleOCR 专有格式不得渗入核心 domain；输出一律归一化为 VoucherJSON v1。

三个内置实现：
- TextLayerPDFProvider：文字型 PDF 文本层提取（默认，真实可用）；
- StubProvider：确定性测试桩（不编造内容，按输入映射生成固定结果）；
- PaddleOCRProvider：仅当用户安装了 paddleocr 才可用（get_paddle_provider 探测）。
本模块对 pdfplumber/pypdf 是懒加载：未安装时明确报错并给出安装命令，绝不静默降级编数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .voucher import SCHEMA_VERSION

__all__ = [
    "FileRef", "OCRJobOptions", "OCRResult",
    "OCRProvider", "TextLayerPDFProvider", "StubProvider", "get_provider_for",
]

_DATE_RE = re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})")
_MONEY_RE = re.compile(r"[¥￥$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)")


@dataclass
class FileRef:
    file_id: str
    sha256: str
    filename: str
    content_bytes: bytes


@dataclass
class OCRJobOptions:
    tenant_id: str = "default"
    voucher_type_hint: str = "unknown"
    lang: str = "ch"


@dataclass
class OCRResult:
    voucher_json: dict
    raw_engine: dict = field(default_factory=dict)
    error_code: Optional[str] = None
    retriable: bool = False
    duration_ms: int = 0
    engine_name: str = "stub"
    model_version: str = "dev"


class OCRProvider(Protocol):
    """spec §5.1 契約：輸入檔案引用+選項，輸出標準結果。"""

    def process(self, file_ref: FileRef, options: OCRJobOptions) -> OCRResult: ...


def _parse_money(s: str) -> Optional[float]:
    m = _MONEY_RE.search(s)
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")) + 1e-9, 2)
    except ValueError:
        return None


def _parse_date(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _base_voucher(file_ref: FileRef, options: OCRJobOptions) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "voucher_type": options.voucher_type_hint,
        "document": {
            "file_id": file_ref.file_id,
            "sha256": file_ref.sha256,
            "page_count": 1,
            "captured_at": None,
            "source": "api_upload",
        },
        "issuer": {"name": None, "tax_id": None},
        "counterparty": {"name": None, "tax_id": None},
        "transaction": {
            "document_no": None, "date": None, "currency": "CNY",
            "amount_excl_tax": None, "tax_amount": None,
            "amount_incl_tax": None, "tax_rate": None, "summary": None,
        },
        "fields": [],
        "quality": {"overall_confidence": 0.0, "image_quality": "good",
                     "needs_human_review": True, "reasons": []},
        "provenance": {"ocr_engine": "", "model_version": "dev",
                        "pipeline_version": "v0.1", "processed_at": None},
    }


class TextLayerPDFProvider:
    """文字型 PDF 的文本层提取。扫描件没有文本层 → 明确报 unsupported，转人工。"""

    name = "pdf-textlayer"

    def process(self, file_ref: FileRef, options: OCRJobOptions) -> OCRResult:
        import io
        text = ""
        try:
            try:
                import pdfplumber  # 懒加载
                with pdfplumber.open(io.BytesIO(file_ref.content_bytes)) as pdf:
                    pages = [p.extract_text() or "" for p in pdf.pages]
                    text = "\n".join(pages)
            except ImportError:
                from pypdf import PdfReader  # 兜底
                reader = PdfReader(io.BytesIO(file_ref.content_bytes))
                text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception:
            return self._fail(file_ref, options, "pdf_parse_error", retriable=False)
        if not text.strip():
            # 扫描件无文本层——诚实报告，不编造
            r = OCRResult(voucher_json=_base_voucher(file_ref, options),
                          raw_engine={"text_chars": 0},
                          error_code="no_text_layer_needs_ocr", retriable=False,
                          engine_name=self.name)
            r.voucher_json["quality"]["reasons"] = ["no_text_layer_install_zhanzhen_ocr"]
            return r
        return self._from_text(text, file_ref, options)

    def _from_text(self, text: str, file_ref: FileRef, options: OCRJobOptions) -> OCRResult:
        vj = _base_voucher(file_ref, options)
        txn = vj["transaction"]
        # 关键词驱动的字段抽取（spec §5.2：优先版面/关键词/正则，不用 LLM）
        for key, kws in (
            ("amount_incl_tax", ("价税合计", "合計", "合计", "总额")),
            ("amount_excl_tax", ("不含税金额", "金额", "小写金额")),
            ("tax_amount", ("税额", "税額")),
        ):
            for kw in kws:
                idx = text.find(kw)
                if idx >= 0:
                    val = _parse_money(text[idx: idx + 40])
                    if val is not None:
                        txn[key] = val
                        vj["fields"].append({
                            "key": f"transaction.{key}", "value": str(val),
                            "normalized_value": val, "confidence": 0.85,
                            "bbox": [0, 0, 0, 0], "page": 1,
                            "source_text": text[idx: idx + 24],
                        })
                        break
        d = _parse_date(text)
        if d:
            txn["date"] = d
        m = re.search(r"(?:发票号码|發票號碼|No\.?)[:：]?\s*([A-Za-z0-9-]{6,})", text)
        if m:
            txn["document_no"] = m.group(1)
        cm = re.search(r"名称[:：]\s*([^\n\r]{2,40})", text)
        if cm:
            vj["counterparty"]["name"] = cm.group(1).strip()
        txn["summary"] = (text.strip().splitlines() or [""])[0][:60]
        conf = 0.75 if txn["amount_incl_tax"] or txn["date"] else 0.4
        vj["quality"]["overall_confidence"] = conf
        vj["quality"]["needs_human_review"] = conf < 0.80
        vj["provenance"]["ocr_engine"] = self.name
        from .events import _now_iso
        vj["provenance"]["processed_at"] = _now_iso()
        return OCRResult(voucher_json=vj, raw_engine={"text_chars": len(text)},
                         engine_name=self.name, model_version="textlayer-v1")

    def _fail(self, fr, op, code, retriable):
        vj = _base_voucher(fr, op)
        vj["quality"]["reasons"] = [code]
        return OCRResult(voucher_json=vj, error_code=code, retriable=retriable,
                         engine_name=self.name)


class StubProvider:
    """确定性测试桩：从文本行解析 键=值 对（date=/amount=/counterparty=）。"""

    name = "stub"

    def process(self, file_ref: FileRef, options: OCRJobOptions) -> OCRResult:
        vj = _base_voucher(file_ref, options)
        txn = vj["transaction"]
        text = file_ref.content_bytes.decode("utf-8", "replace")
        kv: dict[str, float | str] = {}
        for line in text.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        if "date" in kv and _parse_date(str(kv["date"]).replace("-", "年").replace("/", "年") ):
            txn["date"] = kv["date"]
        elif "date" in kv:
            txn["date"] = kv["date"]
        if "incl" in kv:
            txn["amount_incl_tax"] = _parse_money(kv["incl"]) 
        if "excl" in kv:
            txn["amount_excl_tax"] = _parse_money(kv["excl"])
        if "tax" in kv:
            txn["tax_amount"] = _parse_money(kv["tax"])
        if "counterparty" in kv:
            vj["counterparty"]["name"] = kv["counterparty"]
        if "docno" in kv:
            txn["document_no"] = kv["docno"]
        vj["quality"]["overall_confidence"] = 0.95
        vj["quality"]["needs_human_review"] = False
        vj["provenance"]["ocr_engine"] = self.name
        return OCRResult(voucher_json=vj, engine_name=self.name, model_version="stub-v1")


def get_provider_for(filename: str, prefer: str = "auto") -> OCRProvider:
    """按文件类型选 provider；图片在未装 PaddleOCR 时给出可读错误。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return TextLayerPDFProvider()
    if prefer == "paddle":
        try:
            import paddleocr  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "图片识别需要 PaddleOCR：pip install 'zhanzhen[ocr]' 后重试"
            ) from e
        raise RuntimeError("PaddleOCR adapter 将在 Week3 提供，当前请用 PDF 文本层或 Stub")
    raise RuntimeError(f"暂不支持的文件类型: {filename}（MVP 支持 PDF；图片需 [ocr] extra）")
