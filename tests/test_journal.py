"""分录守恒测试：借贷不平不能存在；确认后只能冲销。"""

import unittest

from zhanzhen.journal import JournalEntry, JournalError, JournalLine, suggest_entry


class TestBalanceGuard(unittest.TestCase):
    def test_unbalanced_rejected_at_construction(self):
        with self.assertRaises(JournalError):
            JournalEntry(tenant_id="t", voucher_file_id="v",
                lines=[JournalLine("库存商品", debit=100),
                        JournalLine("银行存款", credit=99)])

    def test_line_debit_credit_both_set_rejected(self):
        with self.assertRaises(JournalError):
            JournalLine("x", debit=10, credit=10)

    def test_negative_rejected(self):
        with self.assertRaises(JournalError):
            JournalLine("x", debit=-5)

    def test_lines_hash_stable_and_sensitive(self):
        e1 = JournalEntry(tenant_id="t", voucher_file_id="v",
            lines=[JournalLine("a", debit=10), JournalLine("b", credit=10)])
        e2 = JournalEntry(tenant_id="t", voucher_file_id="v",
            lines=[JournalLine("a", debit=10), JournalLine("b", credit=10)])
        self.assertEqual(e1.lines_hash, e2.lines_hash)
        e3 = JournalEntry(tenant_id="t", voucher_file_id="v",
            lines=[JournalLine("a", debit=9), JournalLine("b", credit=9)])
        self.assertNotEqual(e1.lines_hash, e3.lines_hash)


class TestSuggest(unittest.TestCase):
    def test_vat_invoice_suggestion_balances(self):
        vj = {"voucher_type": "vat_invoice",
               "document": {"file_id": "f1"},
               "transaction": {"amount_excl_tax": 100, "tax_amount": 13,
                                "amount_incl_tax": 113, "summary": "购料"}}
        e = suggest_entry(vj)
        self.assertIsNotNone(e)
        dr = round(sum(l.debit for l in e.lines), 2)
        cr = round(sum(l.credit for l in e.lines), 2)
        self.assertEqual(dr, cr)
        self.assertEqual(e.status, "draft")

    def test_unknown_type_returns_none_not_guess(self):
        vj = {"voucher_type": "unknown", "document": {"file_id": "f"},
               "transaction": {"amount_incl_tax": 5}}
        self.assertIsNone(suggest_entry(vj))

    def test_missing_amount_returns_none(self):
        vj = {"voucher_type": "vat_invoice", "document": {"file_id": "f"},
               "transaction": {}}
        self.assertIsNone(suggest_entry(vj))


if __name__ == "__main__":
    unittest.main()
