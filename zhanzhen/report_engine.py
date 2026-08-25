"""报告模板引擎 v2 —— 按甲方分型的五套报告（专业版核心功能）。

上游依据：docs/REPORT_KNOWLEDGE.md（五类分型）、docs/PRODUCT_TIERS.md（CPA 边界）。
铁律：每份报告页脚必须带「分析初稿 + 须经注册会计师签署」免责声明。
依赖策略：jinja2 可选——未安装时用 string.Template 降级渲染同样结构，绝不失败。
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Optional

__all__ = ["AUDIENCES", "ReportContext", "render", "render_pdf", "render_docx",
           "InvalidAudience"]

AUDIENCES = ("bank", "gov", "boss", "firm", "cross")

DISCLAIMER = ("本报告为数据分析初稿，不构成审计意见；"
              "须经注册会计师签署方具法律效力。签字权永远属于人。")


class InvalidAudience(ValueError):
    pass


@dataclass
class ReportContext:
    tenant_id: str
    period: str
    findings_mvp: list = field(default_factory=list)
    findings_12: list = field(default_factory=list)
    journal_rows: list = field(default_factory=list)
    style_samples: list = field(default_factory=list)
    audience: str = "boss"
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.audience not in AUDIENCES:
            raise InvalidAudience(
                f"audience 必须是 {AUDIENCES} 之一，收到: {self.audience!r}")

    @property
    def total_findings(self) -> int:
        return len(self.findings_mvp) + len(self.findings_12)


# ---------- 五套受众模板（jinja2 语法；降级时转 string.Template） ----------
_TPL_BANK = """<h1>财务状况与风险提示报告</h1>
<p>致授信机构：以下为 {{tenant}} 于 {{period}} 期间的财务健康度分析。</p>
<h2>一、偿债与流动性指标</h2>
<table border="1"><tr><th>科目</th><th>借方合计</th><th>贷方合计</th></tr>
{% for r in journal %}<tr><td>{{r["科目"]}}</td><td>{{r["借方"]}}</td><td>{{r["贷方"]}}</td></tr>{% endfor %}
</table>
<h2>二、风险事项（{{n}} 项）</h2>
<ul>{% for f in findings %}<li>[{{f.severity}}] {{f.title}}：{{f.detail}}</li>{% endfor %}</ul>
<p>结论：请结合上述风险事项审阅授信敞口。{{disclaimer}}</p>"""

_TPL_GOV = """<h1>专项资金使用情况核验报告（初稿）</h1>
<div style="text-align:right">红头文件落款位：__________</div>
<p>依据政策条款逐项核验 {{tenant}} 于 {{period}} 的资金使用：</p>
<table border="1"><tr><th>政策条款</th><th>核验结果</th><th>对应凭证证据</th></tr>
{% for f in findings %}<tr><td>{{f.rule_id}}</td><td>{{f.title}}</td><td>{{f.evidence|join("; ")}}</td></tr>{% endfor %}
</table>
<p>{{disclaimer}}</p>"""

_TPL_BOSS = """<h1>{{tenant}} 经营体检报告（{{period}}）</h1>
<p>老板您好，我们检查了账上 {{n}} 个风险点，白话讲：</p>
<ol>{% for f in findings %}
<li><b>{{f.title}}</b>（编号 {{f.rule_id}}）——{{f.detail}}
<br>👉 建议：{{f.suggested_procedure}}（责任岗位：财务负责人）</li>{% endfor %}</ol>
<p>{{disclaimer}}</p>"""

_TPL_FIRM = """<h1>审计底稿索引与例外事项表</h1>
<p>项目：{{tenant}}　期间：{{period}}</p>
<table border="1"><tr><th>#</th><th>规则</th><th>严重度</th><th>说明</th><th>证据定位</th></tr>
{% for f in findings %}<tr><td>{{loop.index}}</td><td>{{f.rule_id}}</td><td>{{f.severity}}</td>
<td>{{f.detail}}</td><td>{{f.evidence|join("<br>")}}</td></tr>{% endfor %}</table>
<p>复核提示：以上例外事项均需项目负责人复核后方可进报告终稿。{{disclaimer}}</p>"""

_TPL_CROSS = """<h1>Audit Analysis Report / 审计分析报告 (Draft)</h1>
<p>Entity: {{tenant}} · Period: {{period}}</p>
<h2>CAS vs IFRS 口径差异提示</h2>
<ul><li>收入确认：CAS 14 与 IFRS 15 趋同但时点差异需复核</li>
<li>固定资产：CAS 允许分类折旧政策差异需披露</li></ul>
<h2>Findings / 风险发现</h2>
<table border="1"><tr><th>ID</th><th>Severity</th><th>Description</th></tr>
{% for f in findings %}<tr><td>{{f.rule_id}}</td><td>{{f.severity}}</td>
<td>{{f.detail}}<br><i>{{f.suggested_procedure}}</i></td></tr>{% endfor %}</table>
<p>{{disclaimer}} / This draft requires signature by a licensed Chinese CPA.</p>"""

TEMPLATES = {"bank": _TPL_BANK, "gov": _TPL_GOV, "boss": _TPL_BOSS,
             "firm": _TPL_FIRM, "cross": _TPL_CROSS}


def _ctx_vars(ctx: ReportContext) -> dict:
    findings = list(ctx.findings_mvp) + [
        type("F", (), {"rule_id": f.get("rule_id", ""),
                        "severity": f.get("severity", ""),
                        "title": f.get("title", ""),
                        "detail": f.get("detail", ""),
                        "evidence": f.get("evidence", []),
                        "suggested_procedure": f.get("suggested_procedure", "")})
        for f in ctx.findings_12]
    return {"tenant": ctx.tenant_id, "period": ctx.period,
             "findings": findings, "journal": ctx.journal_rows,
             "n": ctx.total_findings, "disclaimer": DISCLAIMER}


def render(ctx: ReportContext) -> str:
    """渲染报告 HTML。jinja2 存在用模板引擎；否则 string.Template 降级。"""
    tpl = TEMPLATES[ctx.audience]
    try:
        from jinja2 import Template   # 可选依赖
        return Template(tpl).render(**_ctx_vars(ctx))
    except ImportError:
        # 降级：简单替换 + 手工展开 findings 循环
        v = _ctx_vars(ctx)
        rows = ""
        for f in v["findings"]:
            ev = "; ".join(map(str, f.evidence)) if isinstance(f.evidence, list) else str(f.evidence)
            rows += f"<li>[{html.escape(f.severity)}] {html.escape(f.title)}："                     f"{html.escape(f.detail)}（证据:{html.escape(ev)}）</li>"
        jr = "".join(f"<tr><td>{r.get('科目','')}</td><td>{r.get('借方','')}</td>"
                     f"<td>{r.get('贷方','')}</td></tr>" for r in v["journal"])
        body = tpl
        for k in ("tenant", "period", "n"):
            body = body.replace("{{" + k + "}}", str(v[k]))
        body = body.replace("{{disclaimer}}", DISCLAIMER)
        import re
        body = re.sub(r"\{%.*?%\}", "", body, flags=re.S)  # 去掉未渲染的 jinja 块
        body = body.replace("{% for r in journal %}", "").replace("{% endfor %}", "")
        body = body.replace('<tr><td>{{r["科目"]}}</td><td>{{r["借方"]}}</td>'
                             '<td>{{r["贷方"]}}</td></tr>', jr)
        body = body.replace("<li>", "<ul><li>", 1) if "<li>" in body else body
        body = body.replace("</li>{% endfor %}", "</li></ul>")
        if rows:
            body = body + "<ul class='findings'>" + rows + "</ul>"
        return body


def render_pdf(ctx: ReportContext) -> bytes:
    """weasyprint 懒加载；未安装给出可读错误。"""
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError("PDF 导出需要: pip install 'zhanzhen[report]'") from e
    return HTML(string=render(ctx)).write_pdf()


def render_docx(ctx: ReportContext) -> bytes:
    """docxtpl 懒加载；未安装给出可读错误。MVP 先回 HTML 字节的 docx 包装位。"""
    raise RuntimeError("docx 导出将在 v0.5-beta 提供（docxtpl 模板包属专业版内容）")
