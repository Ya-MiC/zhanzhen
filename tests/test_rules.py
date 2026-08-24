"""三条 MVP 规则测试（ENGINEERING_SPEC 8.1）。"""

import unittest

from zhanzhen.rules import RuleEngine


def vj(vid="v1", date="2026-08-01", cp="甲公司", incl=113.0, excl=None, tax=None,
        docno=None, vtype="vat_invoice"):
    txn = {"date": date, "amount_incl_tax": incl,
            "amount_excl_tax": excl if excl is not None else round(incl/1.13, 2),
            "tax_amount": tax, "document_no": docno}
    return {"voucher_type": vtype,
             "document": {"file_id": vid, "sha256": "ab"*32},
             "counterparty": {"name": cp}, "transaction": txn}


class TestAmountConsistency(unittest.TestCase):
    def setUp(self):
        self.eng = RuleEngine(params={"rules": [
            {"rule_id": "R-AMT-001", "version": "1.0", "severity": "high",
              "params": {"tolerance": 0.01}}]})

    def test_balanced_triangle_passes(self):
        self.assertEqual(self.eng.check_amount_consistency(
            [vj(excl=100, tax=13, incl=113)]), [])

    def test_unbalanced_triangle_hits(self):
        fs = self.eng.check_amount_consistency([vj(excl=100, tax=13, incl=113.05)])
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].rule_id, "R-AMT-001")
        self.assertIn("三角不平", fs[0].explanation)
        self.assertTrue(fs[0].evidence_refs[0]["file_sha256"])


class TestDuplicates(unittest.TestCase):
    def setUp(self):
        self.eng = RuleEngine(params={"rules": [
            {"rule_id": "R-DUP-001", "version": "1.0", "severity": "medium",
              "params": {"amount_tolerance": 0.0}}]})

    def test_same_date_cp_amount_flags_second(self):
        a = vj("va", docno="A"); b = vj("vb", docno="B")
        fs = self.eng.check_duplicates([a, b])
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].voucher_id, "vb")     # 只标后到者
        self.assertIn("va", fs[0].explanation)

    def test_different_dates_no_hit(self):
        fs = self.eng.check_duplicates([vj("va", date="2026-08-01"),
                                         vj("vb", date="2026-08-02")])
        self.assertEqual(fs, [])


class TestCompleteness(unittest.TestCase):
    def setUp(self):
        self.eng = RuleEngine(params={"rules": [
            {"rule_id": "R-CMP-001", "version": "1.0", "severity": "high",
              "params": {"required_fields": ["transaction.date",
                                              "transaction.amount_incl_tax"],
                          "require_counterparty": True}}]})

    def test_missing_fields_flagged(self):
        bad = vj(); bad["transaction"]["date"] = None; bad["counterparty"]["name"] = None
        fs = self.eng.check_completeness([bad])
        self.assertEqual(len(fs), 1)
        self.assertIn("date", fs[0].explanation)
        self.assertIn("counterparty.name", fs[0].explanation)


if __name__ == "__main__":
    unittest.main()
