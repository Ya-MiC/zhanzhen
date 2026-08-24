"""分录草稿、借贷平衡硬校验与确认后不可变。

权威规范：ENGINEERING_SPEC §3.4 / §8.1 规则3：
- 分录永远是草稿直到人工确认；
- 借贷不平衡的分录**不能存在**（构造即抛错）；
- JOURNAL_CONFIRMED 后不得 UPDATE：修正 = reversal（原分录不动，关系留痕）；
- 科目建议来自按凭证类型的映射模板（诚实：不是企业会计政策）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from .canonical import canonical_sha256
from .state_machine import assert_transition

__all__ = ["JournalLine", "JournalEntry", "JournalError", "suggest_entry"]

# 科目建议模板（MVP：按凭证类型；企业级映射是未来配置）
_SUGGEST = {
    "vat_invoice": [
        {"account": "1403 原材料 / 或按实际类别", "side": "debit", "ratio": "excl"},
        {"account": "2221 应交税费—应交增值税(进项)", "side": "debit", "ratio": "tax"},
        {"account": "2202 应付账款 / 1002 银行存款", "side": "credit", "ratio": "incl"},
    ],
    "expense_receipt": [
        {"account": "5601 管理费用 / 按部门归集", "side": "debit", "ratio": "excl"},
        {"account": "2221 应交税费—进项(如有)", "side": "debit", "ratio": "tax"},
        {"account": "1001 库存现金 / 1002 银行存款", "side": "credit", "ratio": "incl"},
    ],
    "bank_receipt": [
        {"account": "1002 银行存款", "side": "debit", "ratio": "incl"},
        {"account": "6001 主营业务收入 / 往来科目", "side": "credit", "ratio": "excl"},
        {"account": "2221 应交税费—销项(如有)", "side": "credit", "ratio": "tax"},
    ],
}


class JournalError(Exception):
    pass


@dataclass
class JournalLine:
    account: str
    debit: float = 0.0
    credit: float = 0.0

    def __post_init__(self) -> None:
        self.debit = round(float(self.debit) + 1e-9, 2)
        self.credit = round(float(self.credit) + 1e-9, 2)
        if self.debit < 0 or self.credit < 0:
            raise JournalError("借/贷金额不能为负")
        if self.debit > 0 and self.credit > 0:
            raise JournalError("一行只能记借或记贷其一")


@dataclass
class JournalEntry:
    tenant_id: str
    voucher_file_id: str
    lines: list[JournalLine]
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "draft"          # draft | confirmed | reversed
    summary: str = ""
    reversal_of: Optional[str] = None
    lines_hash: str = ""

    def __post_init__(self) -> None:
        if not self.lines:
            raise JournalError("分录至少一行")
        dr = round(sum(l.debit for l in self.lines), 2)
        cr = round(sum(l.credit for l in self.lines), 2)
        if abs(dr - cr) > 0.001:
            raise JournalError(f"借贷不平: 借方合计 {dr} ≠ 贷方合计 {cr}——分录不能保存")
        self._recalc_hash()

    def _recalc_hash(self) -> None:
        self.lines_hash = canonical_sha256(
            [{"account": l.account, "debit": l.debit, "credit": l.credit} for l in self.lines]
        )

    def confirm(self, current_status_allowed: tuple[str, ...] = ("JOURNAL_DRAFTED",)) -> None:
        """确认分录。调用方负责先 assert_transition(voucher 状态)。"""
        if self.status != "draft":
            raise JournalError(f"只有草稿可确认（当前 {self.status}）")
        self.status = "confirmed"

    def reverse(self, reason: str = "") -> "JournalEntry":
        """已确认分录的唯一修正方式：生成红字冲销分录，原分录不变。"""
        if self.status != "confirmed":
            raise JournalError("只有已确认分录可冲销")
        rev = JournalEntry(
            tenant_id=self.tenant_id,
            voucher_file_id=self.voucher_file_id,
            lines=[JournalLine(l.account, l.credit, l.debit) for l in self.lines],
            status="confirmed",
            summary=f"[冲销 {self.entry_id}] {reason}",
            reversal_of=self.entry_id,
        )
        self.status = "reversed"
        return rev

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id, "tenant_id": self.tenant_id,
            "voucher_file_id": self.voucher_file_id, "status": self.status,
            "summary": self.summary, "reversal_of": self.reversal_of,
            "lines_hash": self.lines_hash,
            "lines": [{"account": l.account, "debit": l.debit, "credit": l.credit}
                       for l in self.lines],
        }


def suggest_entry(voucher_json: dict) -> Optional[JournalEntry]:
    """按凭证类型给出分录草稿建议（永远 draft，永远要人看）。

    金額取 VoucherJSON 三角歸一化後的值；缺金額返回 None（不猜）。
    """
    vtype = voucher_json.get("voucher_type")
    txn = voucher_json.get("transaction") or {}
    excl, tax, incl = txn.get("amount_excl_tax"), txn.get("tax_amount"), txn.get("amount_incl_tax")
    if incl is None:
        return None
    excl = excl if excl is not None else round(incl - (tax or 0), 2)
    tax = tax if tax is not None else round(incl - excl, 2)

    template = _SUGGEST.get(vtype)
    file_id = (voucher_json.get("document") or {}).get("file_id", "?")

    if vtype in ("vat_invoice", "expense_receipt"):
        lines = [JournalLine(template[0]["account"], debit=excl),
                 JournalLine(template[1]["account"], debit=tax),
                 JournalLine(template[2]["account"], credit=incl)]
    elif vtype == "bank_receipt":
        lines = [JournalLine(template[0]["account"], debit=incl)]
        if tax and abs(tax) > 0.001:
            lines.append(JournalLine(template[2]["account"], credit=tax))
        lines.append(JournalLine(template[1]["account"], credit=round(excl + 1e-9, 2)))
    else:
        return None  # unknown 类型不瞎猜科目
    return JournalEntry(tenant_id="", voucher_file_id=file_id, lines=lines,
                         summary=txn.get("summary") or f"{vtype}")
