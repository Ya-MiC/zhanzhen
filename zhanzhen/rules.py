"""规则引擎 —— 三条 MVP 规则的确定性实现。

权威规范：ENGINEERING_SPEC §8.1；参数外置 rules_builtin.yaml（PyYAML 可选：
未安装时用内置同值参数，保证零依赖测试可用）。
铁律：每条 finding 必带 rule_id/rule_version/severity/evidence_refs/explanation；
规则永不修改数据，只报告。LLM 不参与判定（确定性外壳原则）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["Finding", "RuleEngine", "load_params"]


def _default_params() -> dict:
    return {
        "rules": [
            {"rule_id": "R-AMT-001", "name": "金额一致性", "version": "1.0",
             "severity": "high", "params": {"tolerance": 0.01}},
            {"rule_id": "R-DUP-001", "name": "疑似重复凭证", "version": "1.0",
             "severity": "medium",
             "params": {"amount_tolerance": 0.00}},
            {"rule_id": "R-CMP-001", "name": "凭证完整性", "version": "1.0",
             "severity": "high",
             "params": {"required_fields": ["transaction.date", "transaction.amount_incl_tax"],
                         "require_counterparty": True}},
        ]
    }


def load_params(path: Optional[str] = None) -> dict:
    """从 YAML 加载规则参数；未装 PyYAML 或文件缺失时退回内置默认值。"""
    p = path or os.environ.get("ZZ_RULES_YAML", "rules_builtin.yaml")
    try:
        import yaml  # 可选依赖
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and data.get("rules"):
            return data
    except Exception:
        pass
    return _default_params()


@dataclass
class Finding:
    rule_id: str
    rule_version: str
    severity: str            # high|medium|low
    voucher_id: str          # 触发凭证
    explanation: str         # 可读解释（为什么命中）
    evidence_refs: list[dict] = field(default_factory=list)  # [{file_sha256, field?, document_no?}]
    disposition: str = "open"   # open|accepted|rejected|needs_evidence

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "rule_version": self.rule_version,
            "severity": self.severity, "voucher_id": self.voucher_id,
            "explanation": self.explanation,
            "evidence_refs": self.evidence_refs, "disposition": self.disposition,
        }


def _ev(vj: dict, extra: Optional[dict] = None) -> dict:
    d = {"file_sha256": (vj.get("document") or {}).get("sha256")}
    txn = vj.get("transaction") or {}
    if txn.get("document_no"):
        d["document_no"] = txn["document_no"]
    if extra:
        d.update(extra)
    return d


class RuleEngine:
    def __init__(self, params: Optional[dict] = None) -> None:
        self.params = params or load_params()
        self._by_id = {r["rule_id"]: r for r in self.params.get("rules", [])}

    # ---- R-AMT-001 金额一致性 ----
    def check_amount_consistency(self, vouchers: list[dict]) -> list[Finding]:
        rule = self._by_id.get("R-AMT-001")
        if not rule:
            return []
        tol = float(rule["params"].get("tolerance", 0.01))
        out: list[Finding] = []
        for vj in vouchers:
            txn = vj.get("transaction") or {}
            e, t, i = txn.get("amount_excl_tax"), txn.get("tax_amount"), txn.get("amount_incl_tax")
            if None in (e, t, i):
                continue
            if abs(e + t - i) > tol:
                out.append(Finding(
                    rule_id="R-AMT-001", rule_version=rule["version"],
                    severity=rule["severity"], voucher_id=(vj.get("document") or {}).get("file_id", "?"),
                    explanation=(
                        f"金额三角不平：不含税 {e} + 税额 {t} = {round(e+t,2)} ≠ 含税 {i}"
                        f"（差 {round(e+t-i,2)} 元 > 容差 {tol} 元）"
                    ),
                    evidence_refs=[_ev(vj, {"field": "transaction.amount_incl_tax"})],
                ))
        return out

    # ---- R-DUP-001 疑似重复 ----
    def check_duplicates(self, vouchers: list[dict]) -> list[Finding]:
        rule = self._by_id.get("R-DUP-001")
        if not rule or len(vouchers) < 2:
            return []
        amt_tol = float(rule["params"].get("amount_tolerance", 0.0))
        seen: dict[tuple, dict] = {}
        out: list[Finding] = []
        for vj in sorted(vouchers, key=lambda x: (x.get("transaction") or {}).get("date") or ""):
            txn = vj.get("transaction") or {}
            cp = (vj.get("counterparty") or {}).get("name")
            key = (txn.get("date"), cp, txn.get("amount_incl_tax"))
            if None in key:
                continue
            hit = None
            for k, prev in seen.items():
                same_date = k[0] == key[0]
                same_cp = k[1] == key[1]
                close_amt = (k[2] is not None and key[2] is not None
                             and abs(k[2] - key[2]) <= amt_tol)
                if same_date and same_cp and close_amt:
                    hit = prev
                    break
            if hit is not None:
                hid = (hit.get("document") or {}).get("file_id", "?")
                vid = (vj.get("document") or {}).get("file_id", "?")
                out.append(Finding(
                    rule_id="R-DUP-001", rule_version=rule["version"],
                    severity=rule["severity"], voucher_id=vid,
                    explanation=(
                        f"与凭证 {hid} 同日期({key[0]})、同对手方({cp})、"
                        f"同金额({key[2]})——疑似重复报销/重复入账"
                    ),
                    evidence_refs=[_ev(hit), _ev(vj)],
                ))
            else:
                seen[key] = vj
        return out

    # ---- R-CMP-001 完整性 ----
    def check_completeness(self, vouchers: list[dict]) -> list[Finding]:
        rule = self._by_id.get("R-CMP-001")
        if not rule:
            return []
        required = rule["params"].get("required_fields",
                                      ["transaction.date", "transaction.amount_incl_tax"])
        need_cp = bool(rule["params"].get("require_counterparty", True))
        out: list[Finding] = []
        for vj in vouchers:
            missing: list[str] = []
            for path in required:
                cur: Any = vj
                for part in path.split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                    if cur is None:
                        break
                if cur is None:
                    missing.append(path)
            if need_cp and not (vj.get("counterparty") or {}).get("name"):
                missing.append("counterparty.name")
            if missing:
                out.append(Finding(
                    rule_id="R-CMP-001", rule_version=rule["version"],
                    severity=rule["severity"], voucher_id=(vj.get("document") or {}).get("file_id", "?"),
                    explanation=f"关键字段缺失: {', '.join(missing)}——不可进入确认分录",
                    evidence_refs=[_ev(vj)],
                ))
        return out

    def run_all(self, vouchers: list[dict]) -> list[Finding]:
        findings = self.check_amount_consistency(vouchers)
        findings += self.check_duplicates(vouchers)
        findings += self.check_completeness(vouchers)
        return findings
