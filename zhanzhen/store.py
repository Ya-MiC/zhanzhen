"""租户隔离的内存仓储 + JSON 快照持久化。

MVP 单机实现（LIMITATIONS.md 已声明）；接口按 spec §3.2 实体命名，
未来 PostgreSQL 化时保持同名方法即可替换。
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .events import EventLog


class TenantStore:
    def __init__(self, tenant_id: str, data_dir: Optional[str] = None,
                 events: Optional[EventLog] = None) -> None:
        self.tenant_id = tenant_id
        self.data_dir = data_dir
        self.vouchers: dict[str, dict] = {}      # voucher_id -> {state, voucher_json, entry_id}
        self.entries: dict[str, dict] = {}       # entry_id -> JournalEntry.to_dict()
        self.findings: list[dict] = []
        self.events = events or EventLog()
        self.exports: list[dict] = []
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            self._load()

    # ---------- 持久化 ----------
    @property
    def _snapshot_path(self) -> str:
        return os.path.join(self.data_dir or ".", f"snapshot-{self.tenant_id}.json")

    def save(self) -> None:
        if not self.data_dir:
            return
        snap = {
            "tenant_id": self.tenant_id,
            "vouchers": self.vouchers,
            "entries": self.entries,
            "findings": self.findings,
            "exports": self.exports,
            "events": self.events.all(),
        }
        tmp = self._snapshot_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._snapshot_path)

    def _load(self) -> None:
        p = self._snapshot_path
        if not os.path.exists(p):
            return
        try:
            with open(p, encoding="utf-8") as f:
                snap = json.load(f)
            self.vouchers = snap.get("vouchers", {})
            self.entries = snap.get("entries", {})
            self.findings = snap.get("findings", [])
            self.exports = snap.get("exports", [])
            self.events = EventLog(snap.get("events", []))
        except Exception:
            # 快照损坏时不静默清数据：保留现场并抛出，让人来决定
            raise RuntimeError(f"快照损坏且未恢复: {p}（请人工检查后处理）")

    # ---------- 查询 ----------
    def list_vouchers(self, status: Optional[str] = None) -> list[dict]:
        out = []
        for vid, v in self.vouchers.items():
            if status and v["state"] != status:
                continue
            item = {"voucher_id": vid, **{k: v[k] for k in ("state", "entry_id") if v.get(k)}}
            txn = (v.get("voucher_json") or {}).get("transaction") or {}
            item.update({
                "date": txn.get("date"),
                "counterparty": (v["voucher_json"].get("counterparty") or {}).get("name"),
                "amount_incl_tax": txn.get("amount_incl_tax"),
                "document_no": txn.get("document_no"),
                "voucher_type": v["voucher_json"].get("voucher_type"),
                "sha256": (v["voucher_json"].get("document") or {}).get("sha256"),
            })
            out.append(item)
        return out

    def confirmed_vouchers(self) -> list[dict]:
        return [v["voucher_json"] for v in self.vouchers.values()
                if v["state"] in ("RULES_EVALUATED", "EXPORTED", "ARCHIVED")
                or v["state"] in ("JOURNAL_CONFIRMED",)]

    def journal_rows(self) -> list:
        """序时账行集：确认分录(+冲销) x 行，附凭证要素与证据哈希。

        spec 9.1 导出物1 的数据源；report 与 excel 共用。
        """
        rows = []
        for eid, e in self.entries.items():
            vj = {}
            for v in self.vouchers.values():
                if v.get("entry_id") == eid:
                    vj = v.get("voucher_json") or {}
                    break
            txn = vj.get("transaction") or {}
            doc_no = txn.get("document_no") or eid[:8]
            for l in e.get("lines", []):
                rows.append({
                    "日期": txn.get("date") or "",
                    "凭证号": doc_no,
                    "摘要": e.get("summary") or "",
                    "科目": l.get("account", ""),
                    "借方": f"{float(l.get('debit') or 0):.2f}",
                    "贷方": f"{float(l.get('credit') or 0):.2f}",
                    "附件SHA256": (vj.get("document") or {}).get("sha256", ""),
                    "状态": e.get("status", ""),
                })
        return rows

    def all_voucher_jsons(self) -> list[dict]:
        return [v["voucher_json"] for v in self.vouchers.values()]
