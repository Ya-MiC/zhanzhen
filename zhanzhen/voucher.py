"""VoucherJSON v1 結構校驗與歸一化。

權威 schema：action-tree/specs/voucher-json-v1.schema.json。
鐵律：未知值一律 null，**不可編造**；金額不一致時優先懷疑 OCR 而不是悄悄修正。
標準庫實現（不依賴 pydantic，方便零依賴測試；pydantic 模型屬未來 server 層）。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .state_machine import STATES

__all__ = [
    "SCHEMA_VERSION", "VOUCHER_TYPES",
    "new_voucher_json", "validate_voucher_json", "normalize_amounts",
    "needs_review_reasons",
]

SCHEMA_VERSION = "voucher-json/1.0"
VOUCHER_TYPES = ("vat_invoice", "bank_receipt", "expense_receipt", "unknown")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_voucher_json(
    *,
    file_id: str,
    sha256: str,
    source: str = "api_upload",
    page_count: int = 1,
    voucher_type: str = "unknown",
) -> dict:
    """構造一份最小合法 VoucherJSON（其餘字段按契約置 null）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "voucher_type": voucher_type if voucher_type in VOUCHER_TYPES else "unknown",
        "document": {
            "file_id": file_id,
            "sha256": sha256,
            "page_count": page_count,
            "captured_at": None,
            "source": source,
        },
        "issuer": {"name": None, "tax_id": None},
        "counterparty": {"name": None, "tax_id": None},
        "transaction": {
            "document_no": None,
            "date": None,
            "currency": "CNY",
            "amount_excl_tax": None,
            "tax_amount": None,
            "amount_incl_tax": None,
            "tax_rate": None,
            "summary": None,
        },
        "fields": [],
        "quality": {
            "overall_confidence": 0.0,
            "image_quality": "poor",
            "needs_human_review": True,
            "reasons": ["not_processed"],
        },
        "provenance": {
            "ocr_engine": "none",
            "model_version": "none",
            "pipeline_version": "dev",
            "processed_at": None,
        },
    }


def validate_voucher_json(vj: dict) -> list[str]:
    """返回問題列表；空列表 = 合法。只做結構與值域檢查，不做業務判斷。"""
    problems: list[str] = []
    if not isinstance(vj, dict):
        return ["root: 必須是對象"]
    if vj.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 必須為 {SCHEMA_VERSION}")
    if vj.get("voucher_type") not in VOUCHER_TYPES:
        problems.append(f"voucher_type 必須屬於 {VOUCHER_TYPES}")

    doc = vj.get("document") or {}
    if not isinstance(doc.get("file_id"), str) or not doc.get("file_id"):
        problems.append("document.file_id 缺失")
    sha = doc.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        problems.append("document.sha256 必須是 64 位十六進制")

    txn = vj.get("transaction") or {}
    for k in ("amount_excl_tax", "tax_amount", "amount_incl_tax"):
        v = txn.get(k)
        if v is not None and not isinstance(v, (int, float)):
            problems.append(f"transaction.{k} 必須是數字或 null")
    d = txn.get("date")
    if d is not None and not (isinstance(d, str) and _DATE_RE.match(d)):
        problems.append("transaction.date 必須是 YYYY-MM-DD 或 null")

    fields = vj.get("fields")
    if not isinstance(fields, list):
        problems.append("fields 必須是數組")
    else:
        for i, f in enumerate(fields):
            if not isinstance(f, dict) or not f.get("key"):
                problems.append(f"fields[{i}]: 缺 key")
            conf = (f or {}).get("confidence")
            if conf is not None and not (isinstance(conf, (int, float)) and 0 <= conf <= 1):
                problems.append(f"fields[{i}].confidence 必須在 [0,1]")

    q = vj.get("quality") or {}
    oc = q.get("overall_confidence")
    if not (isinstance(oc, (int, float)) and 0 <= oc <= 1):
        problems.append("quality.overall_confidence 必須在 [0,1]")
    if q.get("image_quality") not in ("good", "warning", "poor"):
        problems.append("quality.image_quality 必須是 good|warning|poor")
    return problems


def normalize_amounts(vj: dict, tol: float = 0.01) -> dict:
    """金額三角歸一化：缺角補角；對不上不改數據，只記 reasons。

    規則（spec §8.1 規則1 的前置）：含稅 ≈ 未稅 + 稅額（容差 tol 元）。
    永遠不修改已有非 null 值——歸一化只填空、不糾錯。
    """
    txn = vj.setdefault("transaction", {})
    excl = txn.get("amount_excl_tax")
    tax = txn.get("tax_amount")
    incl = txn.get("amount_incl_tax")

    def _r2(x):
        return round(float(x) + 1e-9, 2)

    if excl is not None and tax is not None and incl is None:
        txn["amount_incl_tax"] = _r2(excl + tax)
    elif incl is not None and tax is not None and excl is None:
        txn["amount_excl_tax"] = _r2(incl - tax)
    elif incl is not None and excl is not None and tax is None:
        txn["tax_amount"] = _r2(incl - excl)

    # 一致性檢查：三值俱全時若超出容差，記入質量原因（不改數）
    vals = [txn.get(k) for k in ("amount_excl_tax", "tax_amount", "amount_incl_tax")]
    if all(v is not None for v in vals):
        if abs(vals[0] + vals[1] - vals[2]) > tol:
            reasons = vj.setdefault("quality", {}).setdefault("reasons", [])
            if "amount_triangle_mismatch" not in reasons:
                reasons.append("amount_triangle_mismatch")
    return vj


def needs_review_reasons(vj: dict, threshold: float = 0.80) -> list[str]:
    """質量門：低置信/缺關鍵字段/影像差/三角不平 → 必須人工覆核（spec §3.4 強制條款）。"""
    reasons: list[str] = []
    q = vj.get("quality") or {}
    txn = vj.get("transaction") or {}
    oc = q.get("overall_confidence") or 0.0
    if oc < threshold:
        reasons.append(f"overall_confidence_below_threshold:{oc:.2f}<{threshold:.2f}")
    if not txn.get("date"):
        reasons.append("date_missing")
    if txn.get("amount_incl_tax") is None:
        reasons.append("amount_missing")
    if not (vj.get("counterparty") or {}).get("name"):
        reasons.append("counterparty_missing")
    if q.get("image_quality") == "poor":
        reasons.append("image_quality_poor")
    if "amount_triangle_mismatch" in (q.get("reasons") or []):
        reasons.append("amount_triangle_mismatch")
    return reasons
