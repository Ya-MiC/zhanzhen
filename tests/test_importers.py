"""鼎信诺/金蝶 账套导入器测试。

- detect_format / import_dingxinuo / import_ledger 全链（内存构造 xlsx）；
- openpyxl 未安装时 xlsx 相关用例 skipUnless 跳过（诚实降级不装假）。
零外部服务依赖：OCR 走 StubProvider，数据落临时目录。
"""

import io
import os
import tempfile
import unittest

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from zhanzhen.importers import VoucherDraft, detect_format, import_dingxinuo
from zhanzhen.service import AuditService

# 鼎信诺「凭证明细」典型表头与三行借贷平衡数据：
# 借 原材料 10000 + 借 进项税 1300 = 贷 应付账款 11300
DXN_HEADERS = ["日期", "凭证号", "摘要", "科目编码", "科目名称",
               "借方", "贷方", "对方单位"]
DXN_ROWS = [
    ["2026-08-01", "记-001", "购入原材料", "1403", "原材料",
     10000.00, "", "华信钢材贸易有限公司"],
    ["2026-08-01", "记-001", "进项税额", "222101", "应交税费—进项",
     1300.00, "", "华信钢材贸易有限公司"],
    ["2026-08-01", "记-001", "货款未付", "2202", "应付账款",
     "", 11300.00, "华信钢材贸易有限公司"],
]


def build_xlsx(headers=DXN_HEADERS, rows=DXN_ROWS,
               sheet_name="凭证明细", with_noise_rows=True):
    """内存构造鼎信诺样式 xlsx；默认附带空行+合计行验证跳过逻辑。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    if with_noise_rows:
        ws.append([None] * len(headers))                       # 全空行

        def col(key):
            return next((i for i, h in enumerate(headers) if key in str(h)), None)

        total = [None] * len(headers)
        for key in ("借方", "贷方"):
            i = col(key)
            if i is not None:
                total[i] = sum((r[i] or 0) if isinstance(r[i], (int, float)) else 0
                               for r in rows if len(r) > i)
        ws.append(["合计"] + total[1:])                         # 合计行
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestDetectFormat(unittest.TestCase):
    """格式识别：xlsx 分支需 openpyxl；CSV/垃圾分支纯标准库。"""

    def test_empty_bytes_unknown(self):
        self.assertEqual(detect_format(b""), "unknown")

    def test_csv_utf8_is_generic(self):
        csv = "日期,凭证号,摘要,借方,贷方\n2026-08-01,记-001,测试,100,\n"
        self.assertEqual(detect_format(csv.encode("utf-8")), "generic_csv")

    def test_csv_gbk_is_generic(self):
        csv = "日期,凭证号,摘要,科目,借方,贷方\n"
        self.assertEqual(detect_format(csv.encode("gbk")), "generic_csv")

    def test_plain_text_unknown(self):
        self.assertEqual(detect_format(b"name,age\nalice,30\n"), "unknown")

    @unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl：pip install 'zhanzhen[excel]'")
    def test_xlsx_dingxinuo_by_header(self):
        self.assertEqual(detect_format(build_xlsx()), "dingxinuo")

    @unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl：pip install 'zhanzhen[excel]'")
    def test_xlsx_dingxinuo_by_sheet_name_only(self):
        # 表头普通、sheet 名含关键词 → 也判鼎信诺
        data = build_xlsx(headers=["A", "B", "C"], rows=[["1", "2", "3"]],
                          sheet_name="凭证明细")
        self.assertEqual(detect_format(data), "dingxinuo")

    @unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl：pip install 'zhanzhen[excel]'")
    def test_xlsx_kingdee_by_subject_code_header(self):
        data = build_xlsx(
            sheet_name="balance",
            headers=["科目编码", "科目名称", "期初余额", "借方", "贷方"],
            rows=[["1002", "银行存款", 5000, 100, 200]])
        self.assertEqual(detect_format(data), "kingdee")


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl：pip install 'zhanzhen[excel]'")
class TestImportDingxinuo(unittest.TestCase):
    def test_parses_three_balanced_rows_and_skips_noise(self):
        drafts = import_dingxinuo(build_xlsx())
        self.assertEqual(len(drafts), 3)            # 空行/合计行已跳过
        d0 = drafts[0]
        self.assertIsInstance(d0, VoucherDraft)
        self.assertEqual((d0.date, d0.voucher_no, d0.summary),
                         ("2026-08-01", "记-001", "购入原材料"))
        self.assertEqual(d0.account, "原材料")       # 模糊匹配命中「科目名称」列
        self.assertAlmostEqual(d0.debit, 10000.00, places=2)
        self.assertEqual(d0.counterparty, "华信钢材贸易有限公司")
        d2 = drafts[2]
        self.assertAlmostEqual(d2.credit, 11300.00, places=2)
        # 三行借贷平衡
        self.assertAlmostEqual(sum(d.debit for d in drafts),
                               sum(d.credit for d in drafts), places=2)

    def test_column_order_tolerance(self):
        headers = ["对方单位", "贷方金额", "借方金额", "记账日期", "凭证编号", "摘要"]
        rows = [["甲公司", "", 500.5, "2026/8/18", "JZ-2026-09", "报销"]]
        drafts = import_dingxinuo(build_xlsx(headers=headers, rows=rows))
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertAlmostEqual(d.debit, 500.50, places=2)
        self.assertEqual((d.date, d.voucher_no, d.counterparty),
                         ("2026-08-18", "JZ-2026-09", "甲公司"))


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl：pip install 'zhanzhen[excel]'")
class TestServiceImportLedger(unittest.TestCase):
    """service 层入口：每行走 ingest→OCR(stub)→draft→confirm 全链。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = AuditService(tenant_id="test-import",
                                data_dir=os.path.join(self.tmp, "d"))

    def test_import_ledger_full_pipeline_balanced(self):
        out = self.svc.import_ledger(build_xlsx())
        self.assertEqual(out["format"], "dingxinuo")
        self.assertEqual(out["imported"], 3, out["errors"])
        self.assertEqual(out["skipped"], 0, out["skipped"])
        self.assertEqual(out["errors"], [])
        # store.entries 借贷合计相等（每行一张平衡凭证：10000+1300+11300）
        entries = list(self.svc.store.entries.values())
        self.assertEqual(len(entries), 3)
        self.assertEqual({e["status"] for e in entries}, {"confirmed"})
        dr = round(sum(l["debit"] for e in entries for l in e["lines"]), 2)
        cr = round(sum(l["credit"] for e in entries for l in e["lines"]), 2)
        self.assertAlmostEqual(dr, cr, places=2)
        self.assertAlmostEqual(dr, 22600.00, places=2)
        # 账套真实科目已替换模板建议行
        accounts = {l["account"] for e in entries for l in e["lines"]}
        self.assertIn("原材料", accounts)
        # 哈希链完整
        iv = self.svc.verify_integrity()
        self.assertTrue(iv["chain_ok"], iv["errors"])

    def test_zero_amount_row_counted_skipped(self):
        rows = DXN_ROWS + [
            ["2026-08-02", "记-002", "无金额占位行", "9999", "待定", "", "", ""],
        ]
        out = self.svc.import_ledger(build_xlsx(rows=rows))
        self.assertEqual(out["imported"], 3)
        self.assertEqual(out["skipped"], 1)

    def test_unsupported_format_reported_not_raised(self):
        out = self.svc.import_ledger(b"name,age\nalice,30\n")
        self.assertEqual(out["format"], "unknown")
        self.assertEqual(out["imported"], 0)
        self.assertTrue(out["errors"])

    def test_single_bad_row_does_not_break_batch(self):
        # 缺日期缺对手方的行过不了完整性确认门 → 进 errors；其余照常导入
        rows = [DXN_ROWS[0],
                ["", "记-00X", "坏行", "", "", 88.00, "", ""]]
        out = self.svc.import_ledger(build_xlsx(rows=rows))
        self.assertEqual(out["imported"], 1, out["errors"])
        self.assertEqual(len(out["errors"]), 1)
        self.assertEqual(out["errors"][0]["voucher_no"], "记-00X")


if __name__ == "__main__":
    unittest.main()
