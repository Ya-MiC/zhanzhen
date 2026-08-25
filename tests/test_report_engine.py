"""报告模板引擎测试：五种受众渲染 + 免责声明 + v2 导出落盘。"""

import os
import tempfile
import unittest

from zhanzhen.report_engine import (
    AUDIENCES, InvalidAudience, ReportContext, render,
)


def _ctx(aud):
    return ReportContext(
        tenant_id="测试公司", period="2026-08", audience=aud,
        findings_12=[{"rule_id": "R001", "severity": "high",
                       "title": "期末突击收入",
                       "detail": "最后10天收入占比100%",
                       "evidence": ["voucher=a1"],
                       "suggested_procedure": "截止性测试"}],
        journal_rows=[{"科目": "6001 主营业务收入", "借方": "0.00", "贷方": "11300.00"}])


class TestReportEngine(unittest.TestCase):
    def test_five_audiences_render_with_disclaimer(self):
        for aud in AUDIENCES:
            html_doc = render(_ctx(aud))
            self.assertIn("注册会计师", html_doc, f"audience={aud} 缺免责声明")
            self.assertIn("分析初稿", html_doc)
            self.assertIn("测试公司", html_doc)

    def test_invalid_audience_rejected(self):
        with self.assertRaises(InvalidAudience):
            render(_ctx("hacker"))

    def test_render_without_jinja2_still_works(self):
        # 降级路径：即使 jinja2 缺失也必须产出含关键字的 HTML
        html_doc = render(_ctx("boss"))
        self.assertIn("<h1>", html_doc)
        self.assertIn("R001", html_doc)

    def test_v2_export_writes_file(self):
        from zhanzhen.service import AuditService
        svc = AuditService(tenant_id="rptv2", data_dir=tempfile.mkdtemp())
        path = svc.export_report_v2(audience="boss")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("注册会计师", body)

    def test_all_audiences_export(self):
        from zhanzhen.service import AuditService
        svc = AuditService(tenant_id="rptall", data_dir=tempfile.mkdtemp())
        for aud in AUDIENCES:
            p = svc.export_report_v2(audience=aud)
            self.assertTrue(os.path.exists(p), aud)


if __name__ == "__main__":
    unittest.main()
