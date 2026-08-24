"""AuditService —— 全流程编排：采集→OCR→覆核→分录→规则→报告。

每次状态迁移同步追加哈希链事件（同一逻辑事务内先改状态后写事件再落盘），
非法操作一律抛错并保持原状态不变。
"""

from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from .canonical import sha256_hex
from .events import EventLog
from .journal import JournalEntry, JournalLine, JournalError, suggest_entry
from .ocr import FileRef, OCRJobOptions, StubProvider, TextLayerPDFProvider, get_provider_for
from .rules import Finding, RuleEngine
from .state_machine import (
    assert_transition, InvalidTransition,
    INGESTED, OCR_QUEUED, OCR_COMPLETED, OCR_FAILED,
    NEEDS_REVIEW, REVIEWED, JOURNAL_DRAFTED, JOURNAL_CONFIRMED,
    RULES_EVALUATED, EXPORTED, ARCHIVED,
)
from .storage import ObjectStore
from .store import TenantStore
from .voucher import needs_review_reasons, new_voucher_json, normalize_amounts, validate_voucher_json

TEMPLATE_VERSION = "zhanzhen-report/1.0"


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class AuditError(Exception):
    """带用户可读信息的业务错误（HTTP 层转 400/409 信封）。"""


class AuditService:
    def __init__(self, tenant_id: str = "default", data_dir: Optional[str] = None) -> None:
        self.tenant_id = tenant_id
        self.data_dir = data_dir or os.environ.get("ZZ_DATA_DIR") or ".zzdata"
        self.objects = ObjectStore(os.path.join(self.data_dir, "objects-root"))
        self.store = TenantStore(tenant_id, data_dir=os.path.join(self.data_dir, "tenants", tenant_id))
        self.rules = RuleEngine()
        self.review_threshold = float(os.environ.get("ZZ_REVIEW_THRESHOLD", "0.80"))

    # ---------- 1. 采集入库 ----------
    def ingest(self, filename: str, content: bytes, source: str = "api_upload") -> str:
        """接收原件：服务端重算哈希→对象存储→建凭证记录(INGESTED)→voucher.created 事件。"""
        if not content:
            raise AuditError("空文件不能入库")
        file_sha = self.objects.put(content)           # 服务端算哈希
        voucher_id = str(uuid.uuid4())
        vj = new_voucher_json(file_id=voucher_id, sha256=file_sha, source=source)
        vj["provenance"]["processed_at"] = None
        self.store.vouchers[voucher_id] = {
            "state": INGESTED,
            "voucher_json": vj,
            "filename": filename,
            "entry_id": None,
        }
        self.store.events.append(
            self.tenant_id, "voucher", voucher_id, "voucher.created",
            payload={"file_id": voucher_id, "sha256": file_sha, "source": source,
                      "filename": filename},
        )
        self.store.save()
        return voucher_id

    # ---------- 2. OCR ----------
    def run_ocr(self, voucher_id: str, provider_name: str = "auto") -> dict:
        rec = self._get(voucher_id)
        assert_transition(rec["state"], OCR_QUEUED)      # INGESTED -> OCR_QUEUED
        self._transition(rec, OCR_QUEUED, "voucher.ocr_queued", {})
        try:
            provider = self._select_provider(rec.get("filename", ""), provider_name)
            result = provider.process(
                FileRef(file_id=voucher_id, sha256=(rec["voucher_json"]["document"]["sha256"]),
                        filename=rec.get("filename", ""), 
                        content_bytes=self.objects.get(rec["voucher_json"]["document"]["sha256"])),
                OCRJobOptions(tenant_id=self.tenant_id),
            )
        except (RuntimeError, FileNotFoundError) as e:
            # 不可盲重试错误：转人工（状态机允许 OCR_FAILED -> NEEDS_REVIEW）
            self._transition(rec, OCR_FAILED, "voucher.ocr_failed",
                              {"error_code": str(e)[:120], "retriable": False})
            self._transition(rec, NEEDS_REVIEW, "voucher.needs_review",
                              {"reasons": [str(e)[:120]]})
            self.store.save()
            raise AuditError(f"OCR 失败: {e}——已转入人工覆核队列") from e

        vj = result.voucher_json
        problems = validate_voucher_json(vj)
        if problems:
            raise AuditError(f"VoucherJSON 校验失败(内部错误): {problems}")
        normalize_amounts(vj)
        reasons = needs_review_reasons(vj, self.review_threshold)
        q = vj["quality"]
        target = NEEDS_REVIEW if reasons else REVIEWED
        self._transition(rec, OCR_COMPLETED, "voucher.ocr_completed",
                          {"overall_confidence": q.get("overall_confidence", 0)})
        if target == NEEDS_REVIEW:
            q["needs_human_review"] = True
            q["reasons"] = sorted(set((q.get("reasons") or []) + reasons))
            self._transition(rec, NEEDS_REVIEW, "voucher.needs_review", {"reasons": reasons})
        else:
            q["needs_human_review"] = False
            self._transition(rec, REVIEWED, "voucher.review_approved",
                              {"reviewer_id": "auto-gate", "reasons": []})
        self.store.save()
        return {"voucher_id": voucher_id, "state": rec["state"], "voucher_json": vj}

    def _select_provider(self, filename: str, prefer: str):
        if prefer == "stub":
            return StubProvider()
        if prefer == "pdf-textlayer":
            return TextLayerPDFProvider()
        lower = filename.lower()
        if lower.endswith(".pdf"):
            return TextLayerPDFProvider()
        raise AuditError(
            f"暂不支持的文件类型: {filename}。MVP 支持 PDF 文本层；图片请安装 zhanzhen[ocr]"
        )

    # ---------- 3. 人工覆核 ----------
    def review(self, voucher_id: str, corrections: dict, reviewer: str = "human",
                approve: bool = True) -> str:
        """覆核：修正字段（逐字段留痕）→ REVIEWED。corrections 例:
        {"transaction.date": "2026-08-01", "transaction.amount_incl_tax": 11300.0,
         "counterparty.name": "某某公司", "voucher_type": "vat_invoice"}"""
        rec = self._get(voucher_id)
        if rec["state"] != NEEDS_REVIEW and rec["state"] != JOURNAL_DRAFTED:
            raise InvalidTransition(
                f"只有 NEEDS_REVIEW/JOURNAL_DRAFTED 可覆核（当前 {rec['state']}）")
        vj = rec["voucher_json"]
        for path, new_val in (corrections or {}).items():
            cur = vj
            parts = path.split(".")
            for p in parts[:-1]:
                cur = cur[p]
            old = cur.get(parts[-1])
            if old != new_val:
                cur[parts[-1]] = new_val
                self.store.events.append(
                    self.tenant_id, "voucher", voucher_id, "voucher.field_corrected",
                    payload={"field": path, "before": old, "after": new_val,
                              "reason": "human review"},
                    actor_type="user", actor_id=reviewer,
                )
        normalize_amounts(vj)
        if approve:
            self._transition(rec, REVIEWED, "voucher.review_approved",
                              {"reviewer_id": reviewer, "reasons": []})
        self.store.save()
        return rec["state"]

    # ---------- 4. 分录 ----------
    def draft_journal(self, voucher_id: str) -> dict:
        rec = self._get(voucher_id)
        assert_transition(rec["state"], JOURNAL_DRAFTED)
        entry = suggest_entry(rec["voucher_json"])
        if entry is None:
            raise AuditError("金额缺失或类型未知——无法生成科目建议，请先补全覆核")
        entry.tenant_id = self.tenant_id
        rec["entry_id"] = entry.entry_id
        self.store.entries[entry.entry_id] = entry.to_dict()
        self._transition(rec, JOURNAL_DRAFTED, "journal.drafted",
                          {"entry_id": entry.entry_id, "lines_hash": entry.lines_hash})
        self.store.save()
        return entry.to_dict()

    def adjust_journal(self, voucher_id: str, lines: list[dict], summary: str = "") -> dict:
        """人工调整草稿分录行（确认前自由改；每行 {account, debit, credit}）。"""
        rec = self._get(voucher_id)
        if rec["state"] != JOURNAL_DRAFTED:
            raise InvalidTransition("只有草稿态可调整分录")
        try:
            jl = [JournalLine(**l) for l in lines]
            entry = JournalEntry(tenant_id=self.tenant_id,
                voucher_file_id=rec["voucher_json"]["document"]["file_id"],
                lines=jl, summary=summary)
        except (TypeError, JournalError) as e:
            raise AuditError(f"分录不合法: {e}") from e
        old = rec.get("entry_id")
        if old:
            self.store.entries.pop(old, None)
        rec["entry_id"] = entry.entry_id
        self.store.entries[entry.entry_id] = entry.to_dict()
        self.store.events.append(self.tenant_id, "journal_entry", entry.entry_id,
            "journal.redrafted", payload={"lines_hash": entry.lines_hash},
            actor_type="user")
        self.store.save()
        return entry.to_dict()

    def confirm_journal(self, voucher_id: str, actor: str = "human") -> dict:
        rec = self._get(voucher_id)
        if rec["state"] != JOURNAL_DRAFTED:
            raise InvalidTransition(f"只有 JOURNAL_DRAFTED 可确认（当前 {rec['state']}）")
        # R-CMP-001 强制：完整性不过不允许确认（spec §8.1 规则3）
        cmp_findings = [f for f in self.rules.check_completeness([rec["voucher_json"]])]
        if cmp_findings:
            raise AuditError(
                f"完整性规则拦截: {cmp_findings[0].explanation}")
        eid = rec.get("entry_id")
        if not eid or eid not in self.store.entries:
            raise AuditError("没有分录草稿——先 draft_journal")
        self.store.entries[eid]["status"] = "confirmed"
        self._transition(rec, JOURNAL_CONFIRMED, "journal.confirmed",
                          {"entry_id": eid, "actor": actor}, actor_type="user", actor_id=actor)
        self.store.save()
        return self.store.entries[eid]

    def reverse_journal(self, voucher_id: str, reason: str, actor: str = "human") -> dict:
        rec = self._get(voucher_id)
        eid = rec.get("entry_id")
        e = self.store.entries.get(eid or "")
        if not e:
            raise AuditError("找不到已确认分录")
        if e["status"] != "confirmed":
            raise AuditError("只有已确认分录可冲销")
        rev_lines = [{"account": l["account"], "debit": l["credit"], "credit": l["debit"]}
                      for l in e["lines"]]
        rev = JournalEntry(tenant_id=self.tenant_id,
            voucher_file_id=e["voucher_file_id"],
            lines=[JournalLine(**l) for l in rev_lines],
            status="confirmed", summary=f"[冲销 {eid}] {reason}", reversal_of=eid)
        e["status"] = "reversed"
        self.store.entries[rev.entry_id] = rev.to_dict()
        rec["entry_id"] = rev.entry_id
        self.store.events.append(self.tenant_id, "journal_entry", eid,
            "journal.reversed", payload={"reversal_of": eid, "new_entry": rev.entry_id,
                                          "reason": reason},
            actor_type="user", actor_id=actor)
        self.store.save()
        return rev.to_dict()

    # ---------- 5. 规则 ----------
    def run_rules(self) -> list[dict]:
        """对全部已确认凭证跑三条规则；新 finding 追加，旧 finding 保留处置历史。"""
        targets = [rec for rec in self.store.vouchers.values()
                    if rec["state"] == JOURNAL_CONFIRMED]
        if not targets:
            return []
        findings = self.rules.run_all([r["voucher_json"] for r in targets])
        out = []
        existing_keys = {(f["rule_id"], f["voucher_id"]) for f in self.store.findings}
        for f in findings:
            d = f.to_dict()
            if (f.rule_id, f.voucher_id) not in existing_keys:
                self.store.findings.append(d)
            out.append(d)
        for rec in targets:
            self._transition(rec, RULES_EVALUATED, "rules.evaluated",
                              {"run_id": str(uuid.uuid4()), "findings_count": len(findings)})
        self.store.save()
        return self.store.findings

    def dispose_finding(self, index: int, disposition: str, actor: str = "human") -> dict:
        if disposition not in ("accepted", "rejected", "needs_evidence"):
            raise AuditError("disposition 必须是 accepted|rejected|needs_evidence")
        f = self.store.findings[index]
        f["disposition"] = disposition
        self.store.events.append(self.tenant_id, "voucher", f["voucher_id"],
            "finding.dispositioned",
            payload={"finding_rule": f["rule_id"], "disposition": disposition},
            actor_type="user", actor_id=actor)
        self.store.save()
        return f

    # ---------- 6. 导出 ----------
    def export_report(self, out_dir: Optional[str] = None, actor: str = "system") -> str:
        from .report import render_html
        job_id = str(uuid.uuid4())
        out_dir = out_dir or os.path.join(self.data_dir, "exports")
        os.makedirs(out_dir, exist_ok=True)
        html = render_html(self.store, job_id=job_id, template_version=TEMPLATE_VERSION)
        cutoff = max((v.get("occurred_at", "") for v in self.store.events.all()), default=_now_iso())
        path = os.path.join(out_dir, f"report-{job_id[:8]}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        self.store.exports.append({"export_job_id": job_id, "kind": "html-report",
            "template_version": TEMPLATE_VERSION, "generated_at": _now_iso(),
            "data_cutoff_at": cutoff, "path": path, "files": {"report.html": sha256_hex(html.encode())}})
        for rec in self.store.vouchers.values():
            if rec["state"] == RULES_EVALUATED:
                self._transition(rec, EXPORTED, "export.completed",
                    {"export_job_id": job_id, "template_version": TEMPLATE_VERSION})
        self.store.events.append(self.tenant_id, "export_job", job_id, "export.completed",
            payload={"template_version": TEMPLATE_VERSION, "path": os.path.basename(path)},
            actor_type=actor)
        self.store.save()
        return path

    def export_journal_excel(self, out_dir: Optional[str] = None) -> str:
        """序时账导出：有 openpyxl 用 XLSX，否则 CSV（诚实降级）。"""
        job_id = str(uuid.uuid4())
        out_dir = out_dir or os.path.join(self.data_dir, "exports")
        os.makedirs(out_dir, exist_ok=True)
        rows = self.journal_rows()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["日期", "凭证号", "摘要", "科目", "借方", "贷方", "附件SHA256", "状态"])
        for r in rows:
            w.writerow([r["日期"], r["凭证号"], r["摘要"], r["科目"], r["借方"], r["贷方"],
                         r["附件SHA256"], r["状态"]])
        # 借贷平衡程序验证（spec §9.1 输出前强制）
        dr = round(sum(float(r["借方"]) for r in rows), 2)
        cr = round(sum(float(r["贷方"]) for r in rows), 2)
        if abs(dr - cr) > 0.01:
            raise AuditError(f"导出拦截：序时账借贷不平 借{dr} 贷{cr}")
        try:
            from openpyxl import Workbook   # 可选依赖
            wb = Workbook(); ws = wb.active; ws.title = "序时账"
            for line in buf.getvalue().splitlines():
                ws.append(next(csv.reader(io.StringIO(line))))
            path = os.path.join(out_dir, f"journal-{job_id[:8]}.xlsx")
            wb.save(path)
        except ImportError:
            path = os.path.join(out_dir, f"journal-{job_id[:8]}.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(buf.getvalue())
        self.store.exports.append({"export_job_id": job_id, "kind": "journal",
            "template_version": TEMPLATE_VERSION, "generated_at": _now_iso(),
            "path": path, "debit_total": dr, "credit_total": cr})
        self.store.save()
        return path

    def journal_rows(self) -> list[dict]:
        """序时账行集（含冲销与原分录，按事件时间排序）。"""
        rows = []
        for eid, e in self.store.entries.items():
            vj = next((v["voucher_json"] for v in self.store.vouchers.values()
                        if v.get("entry_id") == eid), None) or {}
            txn = vj.get("transaction") or {}
            for l in e["lines"]:
                rows.append({
                    "日期": txn.get("date") or "", "凭证号": txn.get("document_no") or eid[:8],
                    "摘要": e.get("summary") or "", "科目": l["account"],
                    "借方": f"{l['debit']:.2f}", "贷方": f"{l['credit']:.2f}",
                    "附件SHA256": (vj.get("document") or {}).get("sha256", ""),
                    "状态": e["status"],
                })
        return rows

    # ---------- 7. 完整性 ----------
    def verify_integrity(self) -> dict:
        ok, errors = self.store.events.verify_chain()
        return {"chain_ok": ok, "errors": errors, "event_count": len(self.store.events.all()),
                 "object_count": sum(1 for _ in iter(self.objects.has, True)) if False else None}

    # ---------- 内部 ----------
    def _get(self, voucher_id: str) -> dict:
        rec = self.store.vouchers.get(voucher_id)
        if not rec:
            raise AuditError(f"凭证不存在: {voucher_id}")
        return rec

    def _transition(self, rec: dict, target: str, event_type: str,
                     payload: dict, actor_type: str = "system", actor_id=None) -> None:
        current = rec["state"]
        assert_transition(current, target)
        rec["state"] = target
        vid = rec["voucher_json"]["document"]["file_id"]
        self.store.events.append(self.tenant_id, "voucher", vid, event_type,
            payload=payload, actor_type=actor_type, actor_id=actor_id)

    # ---------- demo ----------
    def load_demo_data(self) -> list[str]:
        """生成示例账套（确定性文本，经 StubProvider 走完整真实管线）。"""
        samples = [
            {"name": "invoice-001.txt", "type": "vat_invoice", "text":
              "docno=INV-2026-0001\ndate=2026-07-31\nexcl=10000\ntax=1300\nincl=11300\ncounterparty=华信钢材贸易有限公司\n"},
            {"name": "invoice-002.txt", "type": "vat_invoice", "text":
              "docno=INV-2026-0002\ndate=2026-08-18\nexcl=5000\ntax=650\nincl=5650\ncounterparty=蓝天办公用品有限公司\n"},
            {"name": "expense-003.txt", "type": "expense_receipt", "text":
              "docno=EXP-0803\ndate=2026-08-03\nexcl=200\ntax=0\nincl=200\ncounterparty=程伟出租车队\n"},
            {"name": "invoice-004-dup.txt", "type": "vat_invoice", "text":
              "docno=INV-2026-0002B\ndate=2026-08-18\nexcl=5000\ntax=650\nincl=5650\ncounterparty=蓝天办公用品有限公司\n"},
            {"name": "bank-005.txt", "type": "bank_receipt", "text":
              "docno=BK-8812\ndate=2026-08-20\nexcl=80000\ntax=10400\nincl=90400\ncounterparty=恒瑞电子股份有限公司\n"},
            {"name": "invoice-006-bad.txt", "type": "vat_invoice", "text":
              "docno=INV-2026-0006\ndate=2026-08-21\nexcl=3000\ntax=390\nincl=3390.05\ncounterparty=宏图五金交电商行\n"},
        ]
        ids = []
        for s in samples:
            vid = self.ingest(s["name"], s["text"].encode(), source="demo")
            self.run_ocr(vid, provider_name="stub")
            ids.append(vid)
        return ids
