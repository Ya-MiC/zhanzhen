"""端到端管线测试：入库→OCR→覆核→分录→规则→导出，全程哈希链完整。

对应总纲 §26 MVP 与 spec §11 Week5-6 验收语义。零外部依赖（StubProvider）。
"""

import os
import tempfile
import unittest

from zhanzhen.service import AuditService, AuditError
from zhanzhen.state_machine import InvalidTransition


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = AuditService(tenant_id="test", data_dir=os.path.join(self.tmp, "d"))

    def _full_flow_one(self, text, vtype, corrections=None):
        vid = self.svc.ingest(f"{vid_name(text)}.txt", text.encode(), source="test")
        self.svc.run_ocr(vid, provider_name="stub", voucher_type_hint=vtype)
        rec = self.svc.store.vouchers[vid]
        if rec["state"] == "NEEDS_REVIEW":
            self.svc.review(vid, corrections or {}, reviewer="tester")
        self.svc.draft_journal(vid)
        self.svc.confirm_journal(vid, actor="tester")
        return vid

    def test_e2e_demo_book_produces_expected_findings(self):
        ids = self.svc.load_demo_data()
        self.assertEqual(len(ids), 6)
        # 006 三角不平 → 必须进人工覆核（质量门）
        bad = [v for v, r in self.svc.store.vouchers.items()
                if r["state"] == "NEEDS_REVIEW"]
        self.assertEqual(len(bad), 1, "只有 006 应被拦截覆核")
        # 覆核批准（保留错误数据——规则应命中它）
        self.svc.review(bad[0], {}, reviewer="tester")
        for vid, rec in list(self.svc.store.vouchers.items()):
            if rec["state"] == "REVIEWED":
                self.svc.draft_journal(vid)
                self.svc.confirm_journal(vid, actor="tester")
        findings = self.svc.run_rules()
        rules_hit = {f["rule_id"] for f in findings}
        self.assertIn("R-DUP-001", rules_hit)   # 002/004 重复
        self.assertIn("R-AMT-001", rules_hit)   # 006 三角不平
        # 导出与完整性
        html_path = self.svc.export_report(out_dir=self.tmp)
        self.assertTrue(os.path.exists(html_path))
        xl = self.svc.export_journal_excel(out_dir=self.tmp)
        self.assertTrue(os.path.exists(xl))
        iv = self.svc.verify_integrity()
        self.assertTrue(iv["chain_ok"], iv["errors"])

    def test_cannot_confirm_before_review(self):
        vid = self.svc.ingest("x.txt", b"date=2026-08-01\nincl=100\n")
        self.svc.run_ocr(vid, provider_name="stub", voucher_type_hint="expense_receipt")
        rec = self.svc.store.vouchers[vid]
        if rec["state"] == "NEEDS_REVIEW":
            with self.assertRaises(InvalidTransition):
                self.svc.draft_journal(vid)      # 未覆核不得做账

    def test_empty_file_rejected(self):
        with self.assertRaises(AuditError):
            self.svc.ingest("e.txt", b"")

    def test_reverse_creates_balanced_red_letter(self):
        vid = self._full_flow_one(
            "docno=T1\ndate=2026-08-01\nexcl=50\ntax=0\nincl=50\ncounterparty=丙\n",
            "expense_receipt")
        rev = self.svc.reverse_journal(vid, reason="录入错误")
        dr = sum(l["debit"] for l in rev["lines"])
        cr = sum(l["credit"] for l in rev["lines"])
        self.assertAlmostEqual(dr, cr, places=2)
        orig = next(e for e in self.store_entries() if e["status"] == "reversed")
        self.assertEqual(rev["reversal_of"], orig["entry_id"])

    def store_entries(self):
        return list(self.svc.store.entries.values())


def vid_name(text):
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:8]


if __name__ == "__main__":
    unittest.main()
