"""憑證狀態機 v1 —— 權威遷移表。

來源：action-tree/specs/voucher-state-machine-v1.md。
任何非法遷移拋 InvalidTransition；每次遷移必須同步追加一條事件（service 層保證，
本模塊提供 assert_transition 供寫入前調用）。
"""

from __future__ import annotations

__all__ = [
    "STATES", "TRANSITIONS", "InvalidTransition",
    "assert_transition", "can_transition",
]

# ---- 狀態集合（12 態）----
CAPTURED = "CAPTURED"
INGESTED = "INGESTED"
OCR_QUEUED = "OCR_QUEUED"
OCR_COMPLETED = "OCR_COMPLETED"
OCR_FAILED = "OCR_FAILED"
NEEDS_REVIEW = "NEEDS_REVIEW"
REVIEWED = "REVIEWED"
JOURNAL_DRAFTED = "JOURNAL_DRAFTED"
JOURNAL_CONFIRMED = "JOURNAL_CONFIRMED"
RULES_EVALUATED = "RULES_EVALUATED"
EXPORTED = "EXPORTED"
ARCHIVED = "ARCHIVED"

STATES = frozenset({
    CAPTURED, INGESTED, OCR_QUEUED, OCR_COMPLETED, OCR_FAILED,
    NEEDS_REVIEW, REVIEWED, JOURNAL_DRAFTED, JOURNAL_CONFIRMED,
    RULES_EVALUATED, EXPORTED, ARCHIVED,
})

# ---- 合法遷移表（specs/voucher-state-machine-v1.md 原文逐條）----
TRANSITIONS: dict[str, frozenset[str]] = {
    CAPTURED: frozenset({INGESTED}),
    INGESTED: frozenset({OCR_QUEUED}),
    OCR_QUEUED: frozenset({OCR_COMPLETED, OCR_FAILED}),
    OCR_COMPLETED: frozenset({NEEDS_REVIEW, REVIEWED}),
    OCR_FAILED: frozenset({OCR_QUEUED, NEEDS_REVIEW}),  # 可重試錯誤重排隊；壞損檔案轉人工
    NEEDS_REVIEW: frozenset({REVIEWED}),
    REVIEWED: frozenset({JOURNAL_DRAFTED}),
    JOURNAL_DRAFTED: frozenset({JOURNAL_CONFIRMED, REVIEWED}),  # 駁回回覆核
    JOURNAL_CONFIRMED: frozenset({RULES_EVALUATED}),
    RULES_EVALUATED: frozenset({EXPORTED, ARCHIVED}),
    EXPORTED: frozenset({ARCHIVED}),
    ARCHIVED: frozenset(),
}


class InvalidTransition(Exception):
    """非法狀態遷移。"""


def can_transition(current: str, target: str) -> bool:
    if current not in STATES or target not in STATES:
        return False
    return target in TRANSITIONS[current]


def assert_transition(current: str, target: str) -> None:
    """非法遷移直接拋錯——調用方必須先處理再遷移。"""
    if current not in STATES:
        raise InvalidTransition(f"未知當前狀態: {current}")
    if target not in STATES:
        raise InvalidTransition(f"未知目標狀態: {target}")
    if not can_transition(current, target):
        legal = ", ".join(sorted(TRANSITIONS[current])) or "(終態)"
        raise InvalidTransition(
            f"非法遷移 {current} -> {target}；合法去向: {legal}"
        )
