"""12规则移植验证：符号约定/重要性校准/典型命中场景（对照 audit-os 测试语义）。"""

import unittest
from zhanzhen.rules12 import LedgerLine, RuleEngine12


def L(v, d, code, amt, cp="", s=""):
    """amt>0 = 借方；amt<0 = 贷方（audit-os 符号约定）。"""
    if amt >= 0:
        return LedgerLine(voucher_id=v, date=d, account_code=code,
                          debit=round(amt, 2), credit=0.0,
                          counterparty=cp, summary=s, locator="voucher=" + v)
    return LedgerLine(voucher_id=v, date=d, account_code=code,
                      debit=0.0, credit=round(-amt, 2),
                      counterparty=cp, summary=s, locator="voucher=" + v)


class TestRules12(unittest.TestCase):
    def setUp(self):
        self.eng = RuleEngine12()

    def test_materiality_auto_calibration(self):
        lines = [L("v1", "2026-07-01", "6001", -1000000)]
        m = self.eng.effective_materiality(lines)
        self.assertEqual(m, 50000.0)   # 100万*0.5%=5000 < base 5万 → 保底

    def test_materiality_scales_with_revenue(self):
        lines = [L("v1", "2026-07-01", "6001", -20000000)]
        m = self.eng.effective_materiality(lines)
        self.assertEqual(m, 100000.0)  # 2000万*0.5%=10万 > base

    def test_r001_period_end_spike(self):
        lines = []
        for i in range(1, 22):
            lines.append(L("v7", "2026-07-%02d" % i, "6001", -10000))
        for i in range(22, 32):   # 最后10天突击
            lines.append(L("v8", "2026-07-%02d" % i, "6001", -30000))
        fs = [f for f in self.eng.run_all(lines) if f.rule_id == "R001"]
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].severity, "high")   # 300/570 > 50%

    def test_r002_large_amount(self):
        fs = [f for f in self.eng.run_all(
            [L("v1", "2026-08-01", "1002", 500000, cp="大客户")])
            if f.rule_id == "R002"]
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].severity, "high")   # 50万 > 2x5万

    def test_r003_direction_violations(self):
        fs = [f for f in self.eng.run_all(
            [L("v1", "2026-08-01", "6001", 500),
             L("v2", "2026-08-01", "6401", -300)]) if f.rule_id == "R003"]
        self.assertEqual(len(fs), 2)

    def test_r006_counterparty_offset(self):
        lines = [
            L("v1", "2026-08-01", "1122", 60000, cp="关联甲"),
            L("v2", "2026-08-01", "2202", -55000, cp="关联甲"),
        ]
        fs = [f for f in self.eng.run_all(lines) if f.rule_id == "R006"]
        self.assertEqual(len(fs), 1)
        self.assertAlmostEqual(fs[0].amount, 55000, places=2)

    def test_r011_repeat_transactions(self):
        lines = [L("v%d" % i, "2026-08-01", "5602", -800, cp="同一家", s="招待费")
                 for i in range(3)]
        fs = [f for f in self.eng.run_all(lines) if f.rule_id == "R011"]
        self.assertEqual(len(fs), 1)

    def test_r012_roundtrip(self):
        lines = [
            L("v1", "2026-08-01", "1002", 5000, s="付款"),
            L("v2", "2026-08-03", "1002", -5000, s="红字冲销"),
        ]
        fs = [f for f in self.eng.run_all(lines) if f.rule_id == "R012"]
        self.assertEqual(len(fs), 1)

    def test_rule_isolation_on_bad_data(self):
        fs = self.eng.run_all([L("v1", "bad-date", "6001", -100)])
        self.assertIsInstance(fs, list)

    def test_severity_ladder(self):
        from zhanzhen.rules12 import sev_by_amount
        self.assertEqual(sev_by_amount(200000, 50000), "high")
        self.assertEqual(sev_by_amount(50000, 50000), "medium")
        self.assertEqual(sev_by_amount(100, 50000), "low")


if __name__ == "__main__":
    unittest.main()
