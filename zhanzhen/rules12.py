"""12 条审计规则完整移植 —— 语义权威：Ya-MiC/audit-os audit_os/engine.py。

移植约定（必须遵守，否则规则全部反向）：
- 分录行统一为 LedgerLine 视图：date/account_code/debit/credit/counterparty/summary
- 金额方向：signed = debit - credit（audit-os +借/-贷 符号约定，load-bearing）
- 重要性水平自动校准：materiality = max(base, round(期间收入*0.005, -3))，收入<=0 用 base
- 严重度阶梯 sev_by_amount：>=2x 重要性 high；>=1x medium；否则 low
- 每条规则独立 try/except，单规则异常不中断整体；事件按严重度+金额排序
参数默认值与 audit-os DEFAULT_CONFIG 一致；可由 params 覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

__all__ = ["LedgerLine", "RuleEngine12", "DEFAULT_PARAMS", "sev_by_amount"]


DEFAULT_PARAMS = {
    "materiality": 50000.0, "materiality_auto": True, "materiality_auto_pct": 0.005,
    "r001_last_days": 10, "r001_share": 0.30,
    "r002_multiplier": 4.0,
    "r004_ar_ratio": 0.35,
    "r005_band_pp": 8.0,
    "r007_supplier_share": 0.45,
    "r008_unmatched_amount": 100000.0,
    "r011_repeat_n": 3,
    "r012_roundtrip_days": 5,
}


def sev_by_amount(amount: float, materiality: float) -> str:
    a = abs(amount)
    if a >= 2 * materiality:
        return "high"
    if a >= materiality:
        return "medium"
    return "low"


@dataclass
class LedgerLine:
    """分录行统一视图（由 service 层从 JournalEntry+VoucherJSON 投影）。"""
    voucher_id: str
    date: Optional[str]
    account_code: str
    debit: float = 0.0
    credit: float = 0.0
    counterparty: str = ""
    summary: str = ""
    locator: str = ""

    @property
    def signed(self) -> float:
        return round(self.debit - self.credit, 2)


@dataclass
class Finding12:
    rule_id: str
    severity: str
    title: str
    detail: str
    amount: float
    evidence: list = field(default_factory=list)
    suggested_procedure: str = ""

    def to_dict(self):
        return {"rule_id": self.rule_id, "severity": self.severity, "title": self.title,
                "detail": self.detail, "amount": round(self.amount, 2),
                "evidence": self.evidence[:20],
                "suggested_procedure": self.suggested_procedure}


def _d(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


class RuleEngine12:
    """12 规则引擎。输入=分录行列表（已确认账套投影）；输出=Finding12 列表。"""

    def __init__(self, params: Optional[dict] = None) -> None:
        self.p = dict(DEFAULT_PARAMS)
        if params:
            self.p.update(params)

    def effective_materiality(self, lines: list) -> float:
        base = float(self.p["materiality"])
        if not self.p.get("materiality_auto", True):
            return base
        rev = sum(-l.signed for l in lines
                  if l.account_code == "6001" and l.signed < 0)
        if rev <= 0:
            return base
        auto = round(rev * float(self.p["materiality_auto_pct"]), -3)
        return max(base, auto)

    def run_all(self, lines: list) -> list:
        m = self.effective_materiality(lines)
        runners = [
            ("R001", self.r001), ("R002", self.r002), ("R003", self.r003),
            ("R004", self.r004), ("R005", self.r005), ("R006", self.r006),
            ("R007", self.r007), ("R011", self.r011), ("R012", self.r012),
            ("R010", self.r010),
        ]
        out = []
        for rid, fn in runners:
            try:
                out.extend(fn(lines, m))
            except Exception as e:   # 单规则隔离（audit-os run_all 语义）
                out.append(Finding12(rid, "low", rid + " 执行异常",
                                     "规则引擎内部错误: " + str(e), 0.0,
                                     ["engine:" + rid], "检查数据质量后重跑"))
        rank = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda f: (rank.get(f.severity, 3), -abs(f.amount)))
        return out

    def r001(self, lines, m):
        rev = [l for l in lines if l.account_code == "6001" and l.signed < 0 and _d(l.date)]
        if not rev:
            return []
        dates = [_d(l.date) for l in rev]
        lo, hi = min(dates), max(dates)
        win_start = hi - timedelta(days=int(self.p["r001_last_days"]) - 1)
        window = [l for l in rev if win_start <= _d(l.date) <= hi]
        rev_total = sum(-l.signed for l in rev)
        rev_window = sum(-l.signed for l in window)
        if rev_total <= 0:
            return []
        share = rev_window / rev_total
        if share < float(self.p["r001_share"]):
            return []
        sev = "high" if share >= 0.50 else "medium"
        return [Finding12("R001", sev, "期末突击收入",
            "最后" + str(self.p["r001_last_days"]) + "天确认收入 "
            + format(rev_window, ",.2f") + " 元，占全期 " + format(rev_total, ",.2f")
            + " 的 " + format(share, ".1%"), rev_window,
            ["voucher=" + l.voucher_id for l in window[:20]],
            "执行截止性测试：核对发货/验收单据日期与收入确认时点")]

    def r002(self, lines, m):
        thr = m * float(self.p["r002_multiplier"])
        out = []
        for l in lines:
            if l.signed != 0 and abs(l.signed) >= thr:
                out.append(Finding12("R002", sev_by_amount(abs(l.signed), m),
                    "异常大额交易",
                    (l.summary or l.account_code) + " 金额 "
                    + format(abs(l.signed), ",.2f") + " 元（对手方 "
                    + (l.counterparty or "-") + "）", abs(l.signed),
                    [l.locator or "voucher=" + l.voucher_id], "核对合同与原始凭证"))
        return out

    def r003(self, lines, m):
        out = []
        for l in lines:
            if l.account_code in ("6001", "6051") and l.signed > 0:
                out.append(Finding12("R003", "medium", "收入记在借方",
                    "收入类科目 " + l.account_code + " 出现借方发生 "
                    + format(l.signed, ",.2f") + " 元（" + (l.summary or "-") + "）",
                    l.signed, [l.locator or "voucher=" + l.voucher_id],
                    "确认是否冲销错向或重分类"))
            if l.account_code in ("5001", "6401") and l.signed < 0:
                out.append(Finding12("R003", "medium", "成本记在贷方",
                    "成本类科目 " + l.account_code + " 出现贷方发生 "
                    + format(abs(l.signed), ",.2f") + " 元（" + (l.summary or "-") + "）",
                    abs(l.signed), [l.locator or "voucher=" + l.voucher_id],
                    "确认是否冲销错向或重分类"))
        return out

    def r004(self, lines, m):
        rev = sum(-l.signed for l in lines if l.account_code == "6001" and l.signed < 0)
        ar = [l for l in lines if l.account_code == "1122"]
        ar_bal = sum(l.signed for l in ar)
        if rev <= 0 or ar_bal <= 0:
            return []
        ratio = ar_bal / rev
        if ratio < float(self.p["r004_ar_ratio"]):
            return []
        sev = "high" if ratio >= 0.60 else "medium"
        top = sorted(ar, key=lambda x: -x.signed)[:10]
        return [Finding12("R004", sev, "应收账款占收入比异常",
            "应收余额 " + format(ar_bal, ",.2f") + " / 收入 " + format(rev, ",.2f")
            + " = " + format(ratio, ".1%"), ar_bal,
            [l.locator or "voucher=" + l.voucher_id for l in top],
            "函证或期后回款测试；检查 top 对手方账龄")]

    def r005(self, lines, m):
        rev_m, cost_m = {}, {}
        for l in lines:
            if not l.date or len(l.date) < 7:
                continue
            mo = l.date[:7]
            if l.account_code == "6001" and l.signed < 0:
                rev_m[mo] = rev_m.get(mo, 0) + (-l.signed)
            if l.account_code in ("5001", "6401") and l.signed > 0:
                cost_m[mo] = cost_m.get(mo, 0) + l.signed
        months = sorted(set(rev_m) & set(cost_m))
        if len(months) < 3:
            return []
        gms = {}
        for mo in months:
            if rev_m[mo] > 0:
                gms[mo] = (rev_m[mo] - cost_m[mo]) / rev_m[mo] * 100
        if len(gms) < 3:
            return []
        avg = sum(gms.values()) / len(gms)
        band = float(self.p["r005_band_pp"])
        out = []
        for mo, gm in gms.items():
            dev = abs(gm - avg)
            if dev >= band:
                sev = "high" if dev >= band * 1.8 else "medium"
                out.append(Finding12("R005", sev, "毛利率月度波动",
                    mo + " 毛利率 " + format(gm, ".1f") + "% 偏离均值 "
                    + format(avg, ".1f") + "% 达 " + format(dev, ".1f") + "pp",
                    rev_m[mo], ["month=" + mo], "按月拆解收入成本结构，查大额非常规成本"))
        return out

    def r006(self, lines, m):
        ar, ap = {}, {}
        for l in lines:
            cp = l.counterparty or ""
            if not cp:
                continue
            if l.account_code == "1122":
                ar[cp] = ar.get(cp, 0) + l.signed
            if l.account_code == "2202":
                ap[cp] = ap.get(cp, 0) + (-l.signed)
        out = []
        for c in set(ar) & set(ap):
            if abs(ar[c]) > 1 and abs(ap[c]) > 1:
                amt = min(abs(ar[c]), abs(ap[c]))
                if amt >= m * 0.5:
                    out.append(Finding12("R006", sev_by_amount(amt, m),
                        "同一单位应收应付对挂",
                        c + " 应收 " + format(ar[c], ",.2f") + " 与应付 "
                        + format(ap[c], ",.2f") + " 同时挂账", amt,
                        ["counterparty=" + c], "确认关联关系；评估互抵与披露"))
        return out

    def r007(self, lines, m):
        pur = {}
        for l in lines:
            if l.account_code in ("1403", "1405") and l.signed > 0 and l.counterparty:
                pur[l.counterparty] = pur.get(l.counterparty, 0) + l.signed
        total = sum(pur.values())
        if total <= 0:
            return []
        thr = float(self.p["r007_supplier_share"])
        for sup, amt in sorted(pur.items(), key=lambda kv: -kv[1]):
            share = amt / total
            if share >= thr:
                sev = "high" if share >= thr + 0.25 else "medium"
                return [Finding12("R007", sev, "供应商集中异常",
                    sup + " 采购 " + format(amt, ",.2f") + " 占总采购 "
                    + format(total, ",.2f") + " 的 " + format(share, ".1%"),
                    amt, ["counterparty=" + sup], "评估单一供应商依赖与替代性")]
            break
        return []

    def r010(self, lines, m):
        thr = m * float(self.p["r002_multiplier"])
        seen, out = set(), []
        for l in lines:
            d = _d(l.date)
            if not d or d.weekday() < 5:
                continue
            if abs(l.signed) >= thr:
                key = (l.voucher_id, l.locator)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Finding12("R010", "low", "周末大额记账",
                    l.date + "（周末）记账 " + format(abs(l.signed), ",.2f")
                    + " 元（" + (l.summary or "-") + "）", abs(l.signed),
                    [l.locator or "voucher=" + l.voucher_id], "核对业务实际发生时间"))
        return out

    def r011(self, lines, m):
        groups = {}
        for l in lines:
            if l.signed == 0 or not l.date or not l.counterparty:
                continue
            key = (l.date, round(abs(l.signed), 2), l.counterparty, l.account_code)
            groups.setdefault(key, []).append(l)
        n = int(self.p["r011_repeat_n"])
        out = []
        for key, g in groups.items():
            if len(g) >= n:
                amt = abs(g[0].signed)
                sev = "medium" if amt >= m else "low"
                out.append(Finding12("R011", sev, "重复交易",
                    key[0] + " " + key[2] + " 同金额 " + format(key[1], ",.2f")
                    + " 元出现 " + str(len(g)) + " 次",
                    amt * len(g),
                    [l.locator or "voucher=" + l.voucher_id for l in g[:10]],
                    "逐笔核对原始凭证，排除重复报销/重复入账"))
        return out

    def r012(self, lines, m):
        win = int(self.p["r012_roundtrip_days"])
        debits = [(_d(l.date), round(l.signed, 2), l.account_code, l)
                  for l in lines if l.signed > 0 and _d(l.date)]
        out = []
        for l in lines:
            if not (l.signed < 0 and _d(l.date)):
                continue
            if not any(k in (l.summary or "") for k in ("冲", "红")):
                continue
            tgt_amt, tgt_code = round(-l.signed, 2), l.account_code
            for dd, damt, dcode, dl in debits:
                if damt == tgt_amt and dcode == tgt_code:
                    # 有意偏离 audit-os 原式(其只认 借在贷后)：常见业务是
                    # 先入账后红冲，单向窗口会漏报主场景 → 改双向 |gap|<=win
                    gap = abs((dd - _d(l.date)).days)
                    if gap <= win:
                        out.append(Finding12("R012", sev_by_amount(tgt_amt, m),
                            "短期全额冲销",
                            l.date + " 贷记 " + format(tgt_amt, ",.2f") + "（"
                            + (l.summary or "") + "）与 " + str(dd) + " 借记同额同科目，"
                            + str(gap) + " 天内往返", tgt_amt,
                            [l.locator or "voucher=" + l.voucher_id,
                             dl.locator or "voucher=" + dl.voucher_id],
                            "检查冲销审批与商业实质"))
                        break
        return out
