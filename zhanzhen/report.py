"""可追溯 HTML 报告 —— 总纲 §7「高质量报告」的最小落地。

每条结论可反向追溯：报告结论 → finding → 凭证 SHA-256。
导出物必带 template_version / generated_at / data_cutoff_at / export_job_id（spec §9.1）。
零依赖实现；样式内联，双击即开。
"""

from __future__ import annotations

import html
from datetime import datetime, timezone


def _esc(x) -> str:
    return html.escape(str(x if x is not None else "-"))


def render_html(store, *, job_id: str, template_version: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cutoff = max((e.get("occurred_at", "") for e in store.events.all()), default="-")
    ok, errors = store.events.verify_chain()

    # ---- 凭证附件索引（spec §9.1 导出物2）----
    vrows = []
    for vid, rec in store.vouchers.items():
        vj = rec["voucher_json"]
        doc = vj.get("document") or {}
        txn = vj.get("transaction") or {}
        cp = (vj.get("counterparty") or {}).get("name")
        sha = doc.get("sha256", "")
        vrows.append(
            f"<tr><td><code>{_esc(vid[:8])}</code></td>"
            f"<td>{_esc(rec.get('filename'))}</td><td>{_esc(vj.get('voucher_type'))}</td>"
            f"<td>{_esc(txn.get('date'))}</td><td>{_esc(cp)}</td>"
            f"<td class=\"num\">{_esc(txn.get('amount_incl_tax'))}</td>"
            f"<td><span class=\"badge b-{_esc(rec['state'])}\">{_esc(rec['state'])}</span></td>"
            f"<td><code class=\"sha\">{_esc(sha[:16])}…</code></td></tr>")

    # ---- 异常清单（导出物3）----
    frows = []
    sev_cls = {"high": "sev-high", "medium": "sev-med", "low": "sev-low"}
    for f in store.findings:
        evs = "<br>".join(
            f"<code class=\"sha\">{_esc(e.get('file_sha256','')[:16])}…</code>"
            + (f" 单号 {_esc(e['document_no'])}" if e.get("document_no") else "")
            for e in f.get("evidence_refs", []))
        frows.append(
            f"<tr><td><code>{_esc(f['rule_id'])}</code><small>v{_esc(f['rule_version'])}</small></td>"
            f"<td><span class=\"{sev_cls.get(f['severity'],'')}\">{_esc(f['severity'])}</span></td>"
            f"<td><code>{_esc(f['voucher_id'][:8])}</code></td>"
            f"<td>{_esc(f['explanation'])}</td><td>{evs}</td>"
            f"<td>{_esc(f['disposition'])}</td></tr>")

    # ---- 序时账摘要 ----
    jrows = []
    dr_total = cr_total = 0.0
    try:
        rows = store_parent_journal(store)
    except Exception:
        rows = []
    for r in rows:
        dr_total += float(r["借方"] or 0); cr_total += float(r["贷方"] or 0)
        jrows.append(f"<tr><td>{_esc(r['日期'])}</td><td>{_esc(r['凭证号'])}</td>"
                     f"<td>{_esc(r['摘要'])}</td><td>{_esc(r['科目'])}</td>"
                     f"<td class=\"num\">{_esc(r['借方'])}</td><td class=\"num\">{_esc(r['贷方'])}</td></tr>")

    chain_html = (
        '<span class="ok">✔ 事件哈希链完整</span>' if ok
        else f'<span class="bad">✘ 链校验失败: {_esc("; ".join(errors))}</span>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>湛箴审计报告 · {html.escape(job_id[:8])}</title>
<style>
body{{font-family:"Microsoft YaHei",-apple-system,sans-serif;margin:0;background:#f5f6f8;color:#1c2733}}
.wrap{{max-width:1080px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;border-bottom:3px solid #0f4c81;padding-bottom:10px}}
h2{{font-size:16px;margin-top:28px;color:#0f4c81}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th,td{{padding:7px 9px;border:1px solid #e3e7ec;text-align:left;vertical-align:top}}
th{{background:#eef3f8}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.sha{{font-family:Consolas,monospace;font-size:11px;color:#555}}
code{{background:#f0f2f5;padding:1px 4px;border-radius:3px}}
.badge{{padding:2px 7px;border-radius:9px;font-size:11px;background:#dde3ea}}
.b-JOURNAL_CONFIRMED,.b-RULES_EVALUATED{{background:#d4edda}}
.b-NEEDS_REVIEW{{background:#ffe3b3}}
.sev-high{{color:#b02a37;font-weight:bold}} .sev-med{{color:#9a6700;font-weight:bold}}
.ok{{color:#1a7f37;font-weight:bold}} .bad{{color:#b02a37;font-weight:bold}}
.meta{{background:#fff;padding:12px 16px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:18px;line-height:1.9}}
.disc{{margin-top:26px;padding:12px 16px;background:#fdf6e3;border-left:4px solid #d9a406;font-size:12px}}
.totals td{{font-weight:bold;background:#f7f9fb}}
</style></head><body><div class="wrap">
<h1>湛箴 · 审计作业报告（分析初稿）</h1>
<div class="meta">
<b>租户：</b>{_esc(store.tenant_id)}　<b>导出任务：</b><code>{_esc(job_id)}</code><br>
<b>模板版本：</b><code>{_esc(template_version)}</code>　<b>生成时间：</b>{_esc(now)}　<b>数据截止：</b>{_esc(cutoff)}<br>
<b>证据链完整性：</b>{chain_html}
</div>

<h2>一、凭证附件索引（{len(vrows)} 张）</h2>
<table><tr><th>ID</th><th>文件名</th><th>类型</th><th>日期</th><th>对手方</th><th>含税金额</th><th>状态</th><th>证据SHA-256</th></tr>
{''.join(vrows) or '<tr><td colspan="8">无凭证</td></tr>'}</table>

<h2>二、异常与覆核清单（{len(frows)} 条）</h2>
<table><tr><th>规则</th><th>严重度</th><th>凭证</th><th>命中解释</th><th>证据引用</th><th>处置</th></tr>
{''.join(frows) or '<tr><td colspan="6">无异常命中</td></tr>'}</table>

<h2>三、序时账（确认分录）</h2>
<table><tr><th>日期</th><th>凭证号</th><th>摘要</th><th>科目</th><th>借方</th><th>贷方</th></tr>
{''.join(jrows) or '<tr><td colspan="6">暂无确认分录</td></tr>'}
<tr class="totals"><td colspan="4">合计</td><td class="num">{dr_total:.2f}</td><td class="num">{cr_total:.2f}</td></tr>
</table>

<div class="disc">⚠ 本报告为<b>数据分析初稿</b>，不构成审计意见或注册会计师执业结论；
签字权永远属于人。所有结论均可通过 SHA-256 反向追溯至原始凭证。</div>
</div></body></html>"""


def store_parent_journal(store):
    """从 service 层拿序时账行集（避免循环 import 的轻量访问）。"""
    svc_method = getattr(store, "journal_rows", None)
    if callable(svc_method):
        return svc_method()
    # TenantStore 直传时没有 journal_rows——由 events 反查 entries 不做，返回空
    return []
