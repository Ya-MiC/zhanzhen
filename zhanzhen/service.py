"""AuditService —— 全流程编排：采集→OCR→覆核→分录→规则→报告。

每次状态迁移同步追加哈希链事件；非法操作一律抛错并保持原状态不变。
"""

from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from .canonical import sha256_hex
from .journal import JournalEntry, JournalError, JournalLine
from .ocr import FileRef, OCRJobOptions, StubProvider, TextLayerPDFProvider
from .rules import RuleEngine
from .state_machine import (
    INGESTED, JOURNAL_CONFIRMED, JOURNAL_DRAFTED, NEEDS_REVIEW,
    OCR_COMPLETED, OCR_FAILED, OCR_QUEUED, REVIEWED, RULES_EVALUATED,
    ARCHIVED, EXPORTED, InvalidTransition, assert_transition,
)
from .storage import ObjectStore
from .store import TenantStore
from .voucher import (
    needs_review_reasons, new_voucher_json, normalize_amounts,
    validate_voucher_json,
)

TEMPLATE_VERSION = "zhanzhen-report/1.0"


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class AuditError(Exception):
    """带用户可读信息的业务错误（HTTP 层转 400 信封）。"""


class AuditService:
    def __init__(self, tenant_id: str = "default", data_dir: Optional[str] = None) -> None:
        self.tenant_id = tenant_id
        self.data_dir = data_dir or os.environ.get("ZZ_DATA_DIR") or ".zzdata"
        self.objects = ObjectStore(os.path.join(self.data_dir, "objects-root"))
        self.store = TenantStore(
            tenant_id, data_dir=os.path.join(self.data_dir, "tenants", tenant_id))
        self.rules = RuleEngine()
        self.review_threshold = float(os.environ.get("ZZ_REVIEW_THRESHOLD", "0.80"))

    # ---------- 1. 采集入库 ----------
    def ingest(self, filename: str, content: bytes, source: str = "api_upload") -> str:
        """接收原件：服务端重算哈希→对象存储→建凭证记录(INGESTED)→voucher.created 事件。"""
        if not content:
            raise AuditError("空文件不能入库")
        file_sha = self.objects.put(content)           # 服务端算哈希，不信客户端
        voucher_id = str(uuid.uuid4())
        vj = new_voucher_json(file_id=voucher_id, sha256=file_sha, source=source)
        self.store.vouchers[voucher_id] = {
            "state": INGESTED, "voucher_json": vj,
            "filename": filename, "entry_id": None,
        }
        self.store.events.append(
            self.tenant_id, "voucher", voucher_id, "voucher.created",
            payload={"file_id": voucher_id, "sha256": file_sha,
                      "source": source, "filename": filename},
        )
        self.store.save()
        return voucher_id

    # ---------- 2. OCR ----------
    def run_ocr(self, voucher_id: str, provider_name: str = "auto",
                 voucher_type_hint: str = "unknown",
                 provider_instance=None) -> dict:
        """跑 OCR。provider_instance 允许调用方（webapp 的 router=auto）注入
        ocr_router.OcrRouter 选出的引擎实例；为空时按 provider_name 走 _select_provider。"""
        rec = self._get(voucher_id)
        assert_transition(rec["state"], OCR_QUEUED)      # INGESTED -> OCR_QUEUED
        self._transition(rec, OCR_QUEUED, "voucher.ocr_queued",
                          {"provider": provider_instance.name
                           if provider_instance is not None else provider_name})
        try:
            if provider_instance is not None:
                provider = provider_instance
            else:
                provider = self._select_provider(rec.get("filename", ""), provider_name)
            result = provider.process(
                FileRef(file_id=voucher_id,
                        sha256=rec["voucher_json"]["document"]["sha256"],
                        filename=rec.get("filename", ""),
                        content_bytes=self.objects.get(
                            rec["voucher_json"]["document"]["sha256"])),
                OCRJobOptions(tenant_id=self.tenant_id,
                               voucher_type_hint=voucher_type_hint),
            )
        except (RuntimeError, FileNotFoundError) as e:
            self._transition(rec, OCR_FAILED, "voucher.ocr_failed",
                              {"error_code": str(e)[:120], "retriable": False})
            self._transition(rec, NEEDS_REVIEW, "voucher.needs_review",
                              {"reasons": [str(e)[:120]]})
            self.store.save()
            raise AuditError(f"OCR 失败: {e}——已转入人工覆核队列") from e

        vj = result.voucher_json
        rec["voucher_json"] = vj   # OCR 结果必须写回凭证记录（状态与数据同事务推进）
        problems = validate_voucher_json(vj)
        if problems:
            raise AuditError(f"VoucherJSON 校验失败(内部错误): {problems}")
        normalize_amounts(vj)
        reasons = needs_review_reasons(vj, self.review_threshold)
        q = vj["quality"]
        self._transition(rec, OCR_COMPLETED, "voucher.ocr_completed",
                          {"overall_confidence": q.get("overall_confidence", 0),
                            "engine": result.engine_name})
        if reasons:
            q["needs_human_review"] = True
            q["reasons"] = sorted(set((q.get("reasons") or []) + reasons))
            self._transition(rec, NEEDS_REVIEW, "voucher.needs_review",
                              {"reasons": reasons})
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
        """覆核：修正字段（逐字段留痕）→ REVIEWED。

        corrections 例: {"transaction.date": "2026-08-01",
                          "transaction.amount_incl_tax": 11300.0,
                          "counterparty.name": "某某公司"}
        """
        rec = self._get(voucher_id)
        if rec["state"] not in (NEEDS_REVIEW, JOURNAL_DRAFTED):
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
                    self.tenant_id, "voucher", voucher_id,
                    "voucher.field_corrected",
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
                          {"entry_id": entry.entry_id,
                            "lines_hash": entry.lines_hash})
        self.store.save()
        return entry.to_dict()

    def adjust_journal(self, voucher_id: str, lines: list,
                        summary: str = "") -> dict:
        """人工调整草稿分录行（确认前自由改；每行 {account, debit, credit}）。"""
        rec = self._get(voucher_id)
        if rec["state"] != JOURNAL_DRAFTED:
            raise InvalidTransition("只有草稿态可调整分录")
        try:
            jl = [JournalLine(**l) for l in lines]
            entry = JournalEntry(
                tenant_id=self.tenant_id,
                voucher_file_id=rec["voucher_json"]["document"]["file_id"],
                lines=jl, summary=summary)
        except (TypeError, ValueError, JournalError) as e:
            raise AuditError(f"分录不合法: {e}") from e
        old = rec.get("entry_id")
        if old:
            self.store.entries.pop(old, None)
        rec["entry_id"] = entry.entry_id
        self.store.entries[entry.entry_id] = entry.to_dict()
        self.store.events.append(
            self.tenant_id, "journal_entry", entry.entry_id,
            "journal.redrafted", payload={"lines_hash": entry.lines_hash},
            actor_type="user")
        self.store.save()
        return entry.to_dict()

    def confirm_journal(self, voucher_id: str, actor: str = "human") -> dict:
        rec = self._get(voucher_id)
        if rec["state"] != JOURNAL_DRAFTED:
            raise InvalidTransition(
                f"只有 JOURNAL_DRAFTED 可确认（当前 {rec['state']}）")
        cmp_findings = self.rules.check_completeness([rec["voucher_json"]])
        if cmp_findings:
            raise AuditError(f"完整性规则拦截: {cmp_findings[0].explanation}")
        eid = rec.get("entry_id")
        if not eid or eid not in self.store.entries:
            raise AuditError("没有分录草稿——先 draft_journal")
        self.store.entries[eid]["status"] = "confirmed"
        self._transition(rec, JOURNAL_CONFIRMED, "journal.confirmed",
                          {"entry_id": eid}, actor_type="user", actor_id=actor)
        self.store.save()
        return self.store.entries[eid]

    # ---------- 3.5 账套导入（鼎信诺/金蝶 xlsx）----------
    _IMPORT_CLEARING_ACCOUNT = "2202 应付账款 / 往来清账(导入)"

    def import_ledger(self, data: bytes) -> dict:
        """账套文件导入入口：识别格式→逐行 Draft 走完整管线→确认分录。

        每行分录生成确定性文本，经 ingest → run_ocr(stub) → draft_journal
        → confirm_journal 全链（不绕过哈希链/状态机/完整性确认门）；
        有科目列时用 adjust_journal 把模板建议行替换为账套真实科目。
        单笔失败进 errors 不中断整批；无金额行计入 skipped。
        返回 {"format", "imported", "skipped", "errors"}。
        """
        from .importers import detect_format, import_dingxinuo

        out = {"format": detect_format(data), "imported": 0,
               "skipped": 0, "errors": []}
        if out["format"] != "dingxinuo":
            out["errors"].append(
                f"暂不支持的账套格式: {out['format']}——目前支持鼎信诺凭证明细 "
                f"xlsx（xlsx 解析需 pip install 'zhanzhen[excel]'）")
            return out
        try:
            drafts = import_dingxinuo(data)
        except Exception as e:
            out["errors"].append(f"解析鼎信诺文件失败: {e}")
            return out

        for idx, d in enumerate(drafts, start=1):
            label = d.voucher_no or f"row{idx}"
            try:
                amount = round(float(d.debit or 0), 2)
                if amount <= 0:
                    amount = round(float(d.credit or 0), 2)
                if amount <= 0:                     # 无金额行不做账
                    out["skipped"] += 1
                    continue
                text = (
                    f"docno={label}\n"
                    f"date={d.date}\n"
                    f"excl={amount}\ntax=0\nincl={amount}\n"
                    f"counterparty={d.counterparty}\n"
                    f"summary={d.summary or d.account or label}\n"
                )
                vid = self.ingest(f"ledger-{label}.txt", text.encode("utf-8"),
                                  source="excel_import")
                self.run_ocr(vid, provider_name="stub",
                              voucher_type_hint="vat_invoice")
                if self.store.vouchers[vid]["state"] == NEEDS_REVIEW:
                    self.review(vid, {}, reviewer="auto-import")
                self.draft_journal(vid)
                if d.account:
                    # 用账套真实科目替换模板建议行（借贷各一行，保持平衡）
                    is_debit = (d.debit or 0) > 0
                    lines = [
                        ({"account": d.account, "debit": amount, "credit": 0.0}
                         if is_debit else
                         {"account": self._IMPORT_CLEARING_ACCOUNT,
                          "debit": amount, "credit": 0.0}),
                        ({"account": self._IMPORT_CLEARING_ACCOUNT,
                          "debit": 0.0, "credit": amount}
                         if is_debit else
                         {"account": d.account, "debit": 0.0, "credit": amount}),
                    ]
                    try:
                        self.adjust_journal(
                            vid, lines, summary=d.summary or f"导入 {label}")
                    except AuditError:
                        pass                        # 调整失败保留模板建议分录（仍平衡）
                self.confirm_journal(vid, actor="excel-import")
                out["imported"] += 1
            except Exception as e:                  # noqa: BLE001 单笔不中断整批
                out["errors"].append({"row": idx, "voucher_no": label,
                                       "error": str(e)[:200]})
        return out

    def reverse_journal(self, voucher_id: str, reason: str,
                         actor: str = "human") -> dict:
        """已确认分录的唯一修正方式：红字冲销，原分录不可变。"""
        rec = self._get(voucher_id)
        eid = rec.get("entry_id")
        e = self.store.entries.get(eid or "")
        if not e:
            raise AuditError("找不到已确认分录")
        if e["status"] != "confirmed":
            raise AuditError("只有已确认分录可冲销")
        rev_lines = [{"account": l["account"], "debit": l["credit"],
                       "credit": l["debit"]} for l in e["lines"]]
        rev = JournalEntry(
            tenant_id=self.tenant_id,
            voucher_file_id=e["voucher_file_id"],
            lines=[JournalLine(**l) for l in rev_lines],
            status="confirmed", summary=f"[冲销 {eid}] {reason}",
            reversal_of=eid)
        e["status"] = "reversed"
        self.store.entries[rev.entry_id] = rev.to_dict()
        rec["entry_id"] = rev.entry_id
        self.store.events.append(
            self.tenant_id, "journal_entry", eid, "journal.reversed",
            payload={"reversal_of": eid, "new_entry": rev.entry_id,
                      "reason": reason},
            actor_type="user", actor_id=actor)
        self.store.save()
        return rev.to_dict()

    # ---------- 5. 规则 ----------
    def run_rules(self) -> list:
        """对全部已覆核及以后状态的凭证跑三条规则。

        发现风险不以做完分录为前提（spec §8.1：金额一致性在提取三角成立即判）；
        状态机 RULES_EVALUATED 只允许从 JOURNAL_CONFIRMED 进入，故仅对
        已确认凭证推进状态；已覆核未确认的凭证只产出 finding，不改状态。
        新 finding 追加，保留处置历史。
        """
        targets_confirmed = [rec for rec in self.store.vouchers.values()
                              if rec["state"] == JOURNAL_CONFIRMED]
        targets_reviewed = [rec for rec in self.store.vouchers.values()
                             if rec["state"] == REVIEWED]
        pool = [r["voucher_json"] for r in targets_confirmed + targets_reviewed]
        if not pool:
            return []
        findings = self.rules.run_all(pool)
        existing_keys = {(f["rule_id"], f["voucher_id"])
                          for f in self.store.findings}
        for f in findings:
            if (f.rule_id, f.voucher_id) not in existing_keys:
                self.store.findings.append(f.to_dict())
        # 状态机 RULES_EVALUATED 只能从 JOURNAL_CONFIRMED 进入；
        # 已覆核未做账的凭证只产出 finding，不推进状态。
        for rec in targets_confirmed:
            self._transition(rec, RULES_EVALUATED, "rules.evaluated",
                              {"run_id": str(uuid.uuid4()),
                                "findings_count": len(findings)})
        self.store.save()
        return self.store.findings

    def dispose_finding(self, index: int, disposition: str,
                         actor: str = "human") -> dict:
        if disposition not in ("accepted", "rejected", "needs_evidence"):
            raise AuditError("disposition 必须是 accepted|rejected|needs_evidence")
        f = self.store.findings[index]
        f["disposition"] = disposition
        self.store.events.append(
            self.tenant_id, "voucher", f["voucher_id"],
            "finding.dispositioned",
            payload={"finding_rule": f["rule_id"],
                      "disposition": disposition},
            actor_type="user", actor_id=actor)
        self.store.save()
        return f

    # ---------- 6. 导出 ----------
    def export_report(self, out_dir: Optional[str] = None) -> str:
        from .report import render_html
        job_id = str(uuid.uuid4())
        out_dir = out_dir or os.path.join(self.data_dir, "exports")
        os.makedirs(out_dir, exist_ok=True)
        html = render_html(self.store, job_id=job_id,
                            template_version=TEMPLATE_VERSION)
        cutoff = max((e.get("occurred_at", "")
                       for e in self.store.events.all()),
                      default=_now_iso())
        path = os.path.join(out_dir, f"report-{job_id[:8]}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        self.store.exports.append({
            "export_job_id": job_id, "kind": "html-report",
            "template_version": TEMPLATE_VERSION,
            "generated_at": _now_iso(), "data_cutoff_at": cutoff,
            "path": path,
            "files": {"report.html": sha256_hex(html.encode())}})
        for rec in self.store.vouchers.values():
            if rec["state"] == RULES_EVALUATED:
                self._transition(rec, EXPORTED, "export.completed",
                    {"export_job_id": job_id,
                      "template_version": TEMPLATE_VERSION})
        self.store.events.append(self.tenant_id, "export_job", job_id,
            "export.completed",
            payload={"template_version": TEMPLATE_VERSION,
                      "path": os.path.basename(path)})
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
        w.writerow(["日期", "凭证号", "摘要", "科目", "借方", "贷方",
                     "附件SHA256", "状态"])
        for r in rows:
            w.writerow([r[k] for k in ("日期", "凭证号", "摘要", "科目",
                                         "借方", "贷方", "附件SHA256", "状态")])
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
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(buf.getvalue())
        self.store.exports.append({
            "export_job_id": job_id, "kind": "journal",
            "template_version": TEMPLATE_VERSION,
            "generated_at": _now_iso(), "path": path,
            "debit_total": dr, "credit_total": cr})
        self.store.save()
        return path

    def journal_rows(self) -> list:
        return self.store.journal_rows()

    # ---------- 报告 v2（按甲方分型，专业版功能）----------
    def export_report_v2(self, audience: str = "boss",
                          out_dir: Optional[str] = None) -> str:
        """按受众渲染报告并落盘。audience: bank|gov|boss|firm|cross。"""
        from .report_engine import ReportContext, render, InvalidAudience
        job_id = str(uuid.uuid4())
        out_dir = out_dir or os.path.join(self.data_dir, "exports")
        os.makedirs(out_dir, exist_ok=True)
        ctx = ReportContext(
            tenant_id=self.tenant_id,
            period=_now_iso()[:10],
            findings_mvp=list(self.store.findings),
            findings_12=list(self.store.findings12),
            journal_rows=self.journal_rows(),
            style_samples=list(getattr(self.store, "style_samples", [])),
            audience=audience)
        html_doc = render(ctx)
        path = os.path.join(out_dir, f"report-{audience}-{job_id[:8]}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html_doc)
        self.store.exports.append({
            "export_job_id": job_id, "kind": f"report-v2:{audience}",
            "template_version": TEMPLATE_VERSION + "-v2/" + audience,
            "generated_at": _now_iso(), "path": path})
        for rec in self.store.vouchers.values():
            if rec["state"] == RULES_EVALUATED:
                self._transition(rec, EXPORTED, "export.completed",
                    {"export_job_id": job_id, "audience": audience})
        self.store.save()
        return path

    # ---------- 8. 12条规则（audit-os 语义完整移植）----------
    def _ledger_lines(self) -> list:
        """把已确认分录+凭证要素投影成 rules12.LedgerLine 视图。

        科目编码取自行内 account 字段的前4位数字（如 "1403 原材料"→"1403"），
        映射不到标准科目时为空串——R003 等方向规则自动跳过未映射行。
        """
        from .rules12 import LedgerLine

        def _code(account: str) -> str:
            digits = ""
            for ch in account or "":
                if ch.isdigit():
                    digits += ch
                else:
                    break
            return digits[:4]

        lines = []
        for eid, e in self.store.entries.items():
            vj = {}
            for v in self.store.vouchers.values():
                if v.get("entry_id") == eid:
                    vj = v.get("voucher_json") or {}
                    break
            txn = vj.get("transaction") or {}
            cp = (vj.get("counterparty") or {}).get("name") or ""
            for n, l in enumerate(e.get("lines", []), start=1):
                lines.append(LedgerLine(
                    voucher_id=eid,
                    date=txn.get("date"),
                    account_code=_code(l.get("account", "")),
                    debit=float(l.get("debit") or 0),
                    credit=float(l.get("credit") or 0),
                    counterparty=cp,
                    summary=e.get("summary") or "",
                    locator="voucher=%s#line%d" % (eid[:8], n)))
        return lines

    def run_rules12(self) -> list:
        """对全部确认分录跑 12 条规则（audit-os 完整语义）。"""
        from .rules12 import RuleEngine12
        lines = self._ledger_lines()
        if not lines:
            return []
        engine = getattr(self, "_engine12", None)
        if engine is None:
            engine = RuleEngine12()
            self._engine12 = engine
        findings = engine.run_all(lines)
        dicts = [f.to_dict() for f in findings]
        existing = {(f["rule_id"], f.get("detail"))
                     for f in self.store.findings12}
        for d in dicts:
            if (d["rule_id"], d["detail"]) not in existing:
                self.store.findings12.append(d)
        self.store.save()
        return self.store.findings12

    # ---------- 7. 完整性 ----------
    def verify_integrity(self) -> dict:
        ok, errors = self.store.events.verify_chain()
        return {"chain_ok": ok, "errors": errors,
                 "event_count": len(self.store.events.all())}

    # ---------- 内部 ----------
    def _get(self, voucher_id: str) -> dict:
        rec = self.store.vouchers.get(voucher_id)
        if not rec:
            raise AuditError(f"凭证不存在: {voucher_id}")
        return rec

    def _transition(self, rec: dict, target: str, event_type: str,
                     payload: dict, actor_type: str = "system",
                     actor_id=None) -> None:
        current = rec["state"]
        assert_transition(current, target)
        rec["state"] = target
        vid = rec["voucher_json"]["document"]["file_id"]
        self.store.events.append(self.tenant_id, "voucher", vid,
            event_type, payload=payload,
            actor_type=actor_type, actor_id=actor_id)

    # ---------- demo ----------
    def load_demo_data(self) -> list:
        """示例账套（确定性文本经 StubProvider 走真实管线）。

        样本设计：002 与 004 同日同对手同金额 → R-DUP-001；
        006 三角不平 0.05 元 → 先进人工覆核，批准后 → R-AMT-001。
        """
        samples = [
            ("invoice-001.txt", "vat_invoice",
             "docno=INV-2026-0001\ndate=2026-07-31\nexcl=10000\ntax=1300\nincl=11300\ncounterparty=华信钢材贸易有限公司\n"),
            ("invoice-002.txt", "vat_invoice",
             "docno=INV-2026-0002\ndate=2026-08-18\nexcl=5000\ntax=650\nincl=5650\ncounterparty=蓝天办公用品有限公司\n"),
            ("expense-003.txt", "expense_receipt",
             "docno=EXP-0803\ndate=2026-08-03\nexcl=200\ntax=0\nincl=200\ncounterparty=程伟出租车队\n"),
            ("invoice-004-dup.txt", "vat_invoice",
             "docno=INV-2026-0002B\ndate=2026-08-18\nexcl=5000\ntax=650\nincl=5650\ncounterparty=蓝天办公用品有限公司\n"),
            ("bank-005.txt", "bank_receipt",
             "docno=BK-8812\ndate=2026-08-20\nexcl=80000\ntax=10400\nincl=90400\ncounterparty=恒瑞电子股份有限公司\n"),
            ("invoice-006-bad.txt", "vat_invoice",
             "docno=INV-2026-0006\ndate=2026-08-21\nexcl=3000\ntax=390\nincl=3390.05\ncounterparty=宏图五金交电商行\n"),
        ]
        ids = []
        for name, vtype, text in samples:
            vid = self.ingest(name, text.encode(), source="demo")
            self.run_ocr(vid, provider_name="stub", voucher_type_hint=vtype)
            ids.append(vid)
        return ids


from .journal import suggest_entry  # noqa: E402  (底部导入避免循环依赖说明见 ARCHITECTURE)
