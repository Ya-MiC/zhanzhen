"""手机采集包 → 工作台收包 端到端测试（spec §6 工作流）。"""

import base64
import os
import tempfile
import unittest

from zhanzhen.service import AuditService


class TestCaptureBatch(unittest.TestCase):
    def setUp(self):
        self.svc = AuditService(tenant_id="cap", data_dir=tempfile.mkdtemp())

    def test_capture_pack_ingest_recomputes_hash(self):
        content = "date=2026-08-25\nincl=990\ncounterparty=测试商户\n".encode("utf-8")
        pack = {"items": [{
            "filename": "photo-1.jpg", "content_b64": base64.b64encode(content).decode(),
            "captured_at": "2026-08-25T10:00:00Z", "note": "午餐发票"}]}
        # 模拟 webapp 层逻辑：服务端重算哈希入库
        vid = self.svc.ingest(pack["items"][0]["filename"], content,
                               source="android_camera")
        rec = self.svc.store.vouchers[vid]
        from zhanzhen.canonical import sha256_hex
        self.assertEqual(rec["voucher_json"]["document"]["sha256"],
                          sha256_hex(content))
        self.assertEqual(rec["voucher_json"]["document"]["source"],
                          "android_camera")

    def test_style_sample_roundtrip(self):
        s = {"title": "2025年度审计报告-某贸易公司", "text": "x" * 100}
        self.svc.store.style_samples.append(s)
        self.svc.store.save()
        # 重开实例验证快照往返
        svc2 = AuditService(tenant_id="cap", data_dir=self.svc.data_dir)
        self.assertEqual(len(svc2.store.style_samples), 1)
        self.assertEqual(svc2.store.style_samples[0]["title"], s["title"])


if __name__ == "__main__":
    unittest.main()
