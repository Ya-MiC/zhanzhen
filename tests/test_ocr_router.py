"""OCR 三级降级链路由器测试（docs/OCR_STRATEGY.md §2 的软件化）。

覆盖：pdf→文本层选路；txt→stub 兼容（含完整管线）；无引擎环境图片
→ NEEDS_SERVER 明确错误；①②③选择顺序；tesseract/paddle 适配器行为；
webapp POST /v1/vouchers/{id}/ocr?router=auto 端到端。
全程不依赖真实 tesseract / paddleocr（mock 注入），保持零外部依赖可跑。
"""

import sys
import tempfile
import types
import unittest
from unittest import mock

from zhanzhen.ocr import FileRef, OCRJobOptions, StubProvider, TextLayerPDFProvider
from zhanzhen.ocr_router import (
    NeedsServerError,
    OcrRouter,
    PaddleProvider,
    TesseractProvider,
)
from zhanzhen.service import AuditService

try:
    from fastapi.testclient import TestClient
    import zhanzhen.webapp as webapp
except Exception:                                    # pragma: no cover
    TestClient = None


def _file_ref(filename="photo.jpg", content=b"\xff\xd8fake-image-bytes"):
    return FileRef(file_id="f1", sha256="a" * 64, filename=filename,
                   content_bytes=content)


class TestRouteSelection(unittest.TestCase):
    """路由决策：按输入类型与引擎可用性自动选路。"""

    def test_pdf_routes_to_text_layer(self):
        provider, chain = OcrRouter().route("invoice-2026-08.pdf")
        self.assertIsInstance(provider, TextLayerPDFProvider)
        self.assertEqual(chain, ["pdf-textlayer"])

    def test_txt_stub_compat_end_to_end(self):
        """txt 走 stub 桩，且路由选出的实例能跑通既有 service 管线。"""
        provider, chain = OcrRouter().route("notes.txt")
        self.assertIsInstance(provider, StubProvider)
        self.assertEqual(chain, ["stub"])
        svc = AuditService(tenant_id="router", data_dir=tempfile.mkdtemp())
        vid = svc.ingest("notes.txt", b"docno=T-9\ndate=2026-08-25\nincl=113\n")
        out = svc.run_ocr(vid, provider_instance=provider)
        self.assertEqual(out["voucher_json"]["transaction"]["amount_incl_tax"], 113.0)

    def test_image_without_engines_returns_needs_server(self):
        router = OcrRouter(tesseract_probe=lambda: None,
                           paddle_probe=lambda: False)
        with self.assertRaises(NeedsServerError) as cm:
            router.route("receipt.png")
        self.assertEqual(cm.exception.code, "NEEDS_SERVER")
        # 可读指引：三种出路都要说清楚
        msg = str(cm.exception)
        for hint in ("tesseract", "paddleocr", "zhanzhen[ocr]"):
            self.assertIn(hint, msg)

    def test_route_selection_order(self):
        """①双引擎可用优先系统级 tesseract → ②缺席降级 PaddleOCR → ③全缺 NEEDS_SERVER。"""
        both = OcrRouter(tesseract_probe=lambda: "/usr/bin/tesseract",
                         paddle_probe=lambda: True)
        p1, c1 = both.route("receipt.png")
        self.assertEqual(c1, ["tesseract-cli"])
        self.assertIsInstance(p1, TesseractProvider)

        only_paddle = OcrRouter(tesseract_probe=lambda: None,
                                paddle_probe=lambda: True)
        p2, c2 = only_paddle.route("receipt.png")
        self.assertEqual(c2, ["paddleocr"])
        self.assertIsInstance(p2, PaddleProvider)

        none = OcrRouter(tesseract_probe=lambda: None, paddle_probe=lambda: False)
        with self.assertRaises(NeedsServerError):
            none.route("receipt.jpg")

    def test_unsupported_type_rejected_honestly(self):
        with self.assertRaises(ValueError):
            OcrRouter().route("scan.tiff")


class TestTesseractProvider(unittest.TestCase):
    def test_process_calls_cli_and_extracts_via_from_text(self):
        fake = mock.Mock(returncode=0,
                          stdout="价税合计 ¥11300\n2026年08月25日\n".encode("utf-8"),
                          stderr=b"")
        with mock.patch("zhanzhen.ocr_router.subprocess.run",
                        return_value=fake) as run_mock:
            res = TesseractProvider(binary="/usr/bin/tesseract").process(
                _file_ref(), OCRJobOptions())
        argv = run_mock.call_args[0][0]
        self.assertEqual(argv[0], "/usr/bin/tesseract")
        self.assertIn("-l", argv)
        self.assertIn("chi_sim", argv)          # 默认中文简体模型
        # 输出走既有 _from_text 抽取管线 → 归一化 VoucherJSON 字段
        self.assertEqual(res.engine_name, "tesseract-cli")
        self.assertEqual(res.voucher_json["transaction"]["amount_incl_tax"], 11300.0)
        self.assertEqual(res.voucher_json["transaction"]["date"], "2026-08-25")

    def test_missing_binary_raises_needs_server(self):
        with mock.patch("zhanzhen.ocr_router.probe_tesseract", return_value=None):
            with self.assertRaises(NeedsServerError):
                TesseractProvider().process(_file_ref(), OCRJobOptions())

    def test_cli_failure_raises_readable_runtime_error(self):
        fake = mock.Mock(returncode=1, stdout=b"", stderr=b"error: no pages")
        with mock.patch("zhanzhen.ocr_router.subprocess.run", return_value=fake):
            with self.assertRaises(RuntimeError) as cm:
                TesseractProvider(binary="/usr/bin/tesseract").process(
                    _file_ref(), OCRJobOptions())
        self.assertIn("tesseract", str(cm.exception))


class TestPaddleProvider(unittest.TestCase):
    def test_import_failure_gives_readable_error(self):
        """探测通过但加载失败 → 可读 RuntimeError 指向安装命令，绝不编数据。"""
        saved = sys.modules.get("paddleocr")
        sys.modules["paddleocr"] = None          # 使 import 抛 ImportError（模拟未安装）
        try:
            with self.assertRaises(RuntimeError) as cm:
                PaddleProvider().process(_file_ref(), OCRJobOptions())
        finally:
            if saved is not None:
                sys.modules["paddleocr"] = saved
            else:
                sys.modules.pop("paddleocr", None)
        self.assertIn("zhanzhen[ocr]", str(cm.exception))

    def test_success_calls_engine_and_parses_lines(self):
        fake_mod = types.ModuleType("paddleocr")

        class FakeEngine:
            def __init__(self, lang=None, **kw):
                self.lang = lang

            def ocr(self, path, cls=None):
                return [[[[0, 0], ["价税合计 5650", 0.98]],
                         [[0, 1], ["2026年08月18日", 0.97]]]]

        fake_mod.PaddleOCR = FakeEngine
        saved = sys.modules.get("paddleocr")
        sys.modules["paddleocr"] = fake_mod
        try:
            res = PaddleProvider(lang="ch").process(_file_ref(), OCRJobOptions())
        finally:
            if saved is not None:
                sys.modules["paddleocr"] = saved
            else:
                sys.modules.pop("paddleocr", None)
        self.assertEqual(res.engine_name, "paddleocr")
        self.assertEqual(res.voucher_json["transaction"]["amount_incl_tax"], 5650.0)


@unittest.skipUnless(TestClient, "fastapi/httpx 未安装，跳过 HTTP 层测试")
class TestWebappRouterAuto(unittest.TestCase):
    def setUp(self):
        self._saved_svc = webapp._svc
        webapp._svc = AuditService(tenant_id="http", data_dir=tempfile.mkdtemp())
        self.client = TestClient(webapp.app)

    def tearDown(self):
        webapp._svc = self._saved_svc

    def test_router_auto_txt_uses_stub_via_http(self):
        r = self.client.post("/v1/vouchers/upload",
                             files={"file": ("demo.txt", b"incl=88\ndate=2026-08-01\n",
                                             "text/plain")})
        vid = r.json()["voucher_id"]
        resp = self.client.post(f"/v1/vouchers/{vid}/ocr?router=auto")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["fallback_chain"], ["stub"])
        self.assertEqual(body["engine"], "stub")
        self.assertEqual(body["voucher_json"]["transaction"]["amount_incl_tax"], 88.0)

    def test_router_auto_pdf_routes_to_textlayer(self):
        r = self.client.post("/v1/vouchers/upload",
                             files={"file": ("inv.pdf", b"%PDF-1.4 fake", "application/pdf")})
        vid = r.json()["voucher_id"]
        body = self.client.post(f"/v1/vouchers/{vid}/ocr?router=auto").json()
        self.assertEqual(body["fallback_chain"], ["pdf-textlayer"])

    def test_router_auto_image_without_engines_envelope(self):
        r = self.client.post("/v1/vouchers/upload",
                             files={"file": ("photo.jpg", b"\xff\xd8jpgbytes",
                                             "image/jpeg")})
        vid = r.json()["voucher_id"]
        with mock.patch("zhanzhen.ocr_router.probe_tesseract", return_value=None), \
             mock.patch("zhanzhen.ocr_router.probe_paddleocr", return_value=False):
            resp = self.client.post(f"/v1/vouchers/{vid}/ocr?router=auto")
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual(body["code"], "NEEDS_SERVER")
        self.assertIn("tesseract", body["message"])

    def test_manual_mode_still_backward_compatible(self):
        r = self.client.post("/v1/vouchers/upload",
                             files={"file": ("x.txt", b"incl=50\n", "text/plain")})
        vid = r.json()["voucher_id"]
        body = self.client.post(f"/v1/vouchers/{vid}/ocr?provider=stub").json()
        self.assertEqual(body["voucher_json"]["transaction"]["amount_incl_tax"], 50.0)


if __name__ == "__main__":
    unittest.main()
