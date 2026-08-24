""append-only 事件日誌與同聚合哈希同聚合哈希鏈。

權威定義：action-tree/specs/events-v1.md。
強制規則：
1. append-only：任何情況不 UPDATE/DELETE；
2. 同一聚合 sequence 嚴格遞增，previous_event_hash 指向同聚合上一條；
3. event_hash = SHA256(canonical_json(event 去掉 event_hash 欄位))；
4. verify_chain() 可在任意時刻校驗整條鏈未被篡改。
標準庫實現。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from .canonical import canonical_sha256

__all__ = ["EventLog"]


class EventLog:
    """內存事件日誌；持久化由 store 層負責（JSON 快照）。"""

    def __init__(self, events: Optional[list[dict]] = None) -> None:
        self._events: list[dict] = list(events or [])

    # ---------- 寫 ----------
    def append(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Optional[dict] = None,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
    ) -> dict:
        if aggregate_type not in ("voucher", "journal_entry", "export_job"):
            raise ValueError(f"未知聚合類型: {aggregate_type}")
        prev = self._last_of(aggregate_id)
        seq = (prev["sequence"] + 1) if prev else 1
        envelope: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "sequence": seq,
            "event_type": event_type,
            "occurred_at": _now_iso(),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "payload": payload or {},
            "previous_event_hash": prev["event_hash"] if prev else None,
        }
        envelope["event_hash"] = canonical_sha256(
            {k: v for k, v in envelope.items() if k != "event_hash"}
        )
        self._events.append(envelope)
        return dict(envelope)

    # ---------- 讀 ----------
    def all(self) -> list[dict]:
        return list(self._events)

    def for_aggregate(self, aggregate_id: str) -> list[dict]:
        return [e for e in self._events if e["aggregate_id"] == aggregate_id]

    def _last_of(self, aggregate_id: str) -> Optional[dict]:
        for e in reversed(self._events):
            if e["aggregate_id"] == aggregate_id:
                return e
        return None

    # ---------- 校驗 ----------
    def verify_chain(self) -> tuple[bool, list[str]]:
        """校驗每條事件哈希與全鏈連續性。返回 (ok, errors)。"""
        errors: list[str] = []
        last_by_agg: dict[str, dict] = {}
        for e in self._events:
            body = {k: v for k, v in e.items() if k != "event_hash"}
            expect = canonical_sha256(body)
            if expect != e.get("event_hash"):
                errors.append(f"{e.get('event_id')}: event_hash 不匹配（內容被篡改？）")
            prev = last_by_agg.get(e["aggregate_id"])
            if prev is None:
                if e.get("previous_event_hash") is not None:
                    errors.append(f"{e['event_id']}: 聚合首事件的 previous_event_hash 應為 null")
            else:
                if e.get("previous_event_hash") != prev["event_hash"]:
                    errors.append(f"{e['event_id']}: previous_event_hash 斷鏈")
                if e["sequence"] != prev["sequence"] + 1:
                    errors.append(f"{e['event_id']}: sequence 不連續")
            last_by_agg[e["aggregate_id"]] = e
        return (len(errors) == 0), errors


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
