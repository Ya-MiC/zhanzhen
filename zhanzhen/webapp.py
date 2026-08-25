"""FastAPI Web 层 —— spec §7.1 端点子集（单租户开发模式）。

规则：
- 错误统一信封 {code, message, details, trace_id}；不回传堆栈；
- 修改型请求接受 Idempotency-Key 头并落事件 payload；
- tenant 从配置取，不信前端传值。
fastapi 是可选依赖（pip install zhanzhen[web]），模块级不硬 import。
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from .service import AuditService, AuditError
from .state_machine import InvalidTransition

try:
    from fastapi import FastAPI, File, Header, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse
    from pydantic import BaseModel
except ImportError as _e:  # pragma: no cover
    raise ImportError("Web 层需要: pip install 'zhanzhen[web]'") from _e

app = FastAPI(title="湛箴 ZhanZhen Audit OS", version="0.1.0")

_svc: Optional[AuditService] = None


def get_svc() -> AuditService:
    global _svc
    if _svc is None:
        _svc = AuditService(
            tenant_id=os.environ.get("ZZ_TENANT_ID", "default"))
    return _svc


class CorrectionIn(BaseModel):
    corrections: dict = {}
    reviewer: str = "web-user"
    approve: bool = True


@app.get("/", response_class=HTMLResponse)
def index():
    web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
    idx = os.path.join(web_dir, "index.html")
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>湛箴</h1><p>web/index.html 缺失</p>")


@app.exception_handler(AuditError)
async def audit_error(_req, exc: AuditError):
    return JSONR({"code": "audit_error", "message": str(exc),
                   "details": {}, "trace_id": _tid()}, 400)


@app.exception_handler(InvalidTransition)
async def invalid_transition(_req, exc: InvalidTransition):
    return JSONR({"code": "invalid_state_transition", "message": str(exc),
                   "details": {}, "trace_id": _tid()}, 409)


def _tid() -> str:
    return uuid.uuid4().hex[:12]


def JSONR(payload: dict, status: int):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=payload)


# ---------- 上传 ----------
@app.post("/v1/vouchers/upload")
async def upload_voucher(file: UploadFile = File(...),
                          idempotency_key: Optional[str] = Header(default=None)):
    content = await file.read()
    vid = get_svc().ingest(file.filename, content)
    ev = {"idempotency_key": idempotency_key} if idempotency_key else {}
    return {"voucher_id": vid, "state": "INGESTED", **ev}


# ---------- 账套导入 ----------
@app.post("/v1/import/ledger")
async def import_ledger(file: UploadFile = File(...)):
    """上传鼎信诺/金蝶导出的账套文件（multipart file）。

    逐行凭证走完整管线并确认分录；返回
    {format, imported, skipped, errors}——单笔失败不中断整批。
    xlsx 解析需可选依赖：pip install 'zhanzhen[excel]'。
    """
    content = await file.read()
    return get_svc().import_ledger(content)


# ---------- OCR ----------
@app.post("/v1/vouchers/{voucher_id}/ocr")
def run_ocr(voucher_id: str, provider: str = "auto", router: str = "manual"):
    """跑 OCR。

    router=auto 时按 docs/OCR_STRATEGY.md 三级降级链自动选路：
    pdf→文本层；txt→stub 桩；图片→tesseract → PaddleOCR → NEEDS_SERVER。
    选路结果回显 engine/fallback_chain，便于客户端埋点降级率。
    """
    svc = get_svc()
    if router == "auto":
        from .ocr_router import NeedsServerError, OcrRouter
        rec = svc.store.vouchers.get(voucher_id)
        if not rec:
            raise HTTPException(404, "voucher not found")
        try:
            selected, chain = OcrRouter().route(rec.get("filename", ""))
        except NeedsServerError as e:
            # 诚实失败：不编数据，凭证留在 INGESTED 可重试；给出明确安装/升级指引
            return JSONR({"code": "NEEDS_SERVER", "message": str(e),
                           "details": {"voucher_id": voucher_id,
                                        "fallback_chain": [NeedsServerError.code]},
                           "trace_id": _tid()}, 409)
        except ValueError as e:
            return JSONR({"code": "unsupported_file_type", "message": str(e),
                           "details": {}, "trace_id": _tid()}, 400)
        out = svc.run_ocr(voucher_id, provider_name="auto",
                           provider_instance=selected)
        out["engine"] = selected.name
        out["fallback_chain"] = chain
        return out
    return svc.run_ocr(voucher_id, provider_name=provider)


# ---------- 列表/详情 ----------
@app.get("/v1/vouchers")
def list_vouchers(status: Optional[str] = None):
    return get_svc().store.list_vouchers(status)


@app.get("/v1/vouchers/{voucher_id}")
def get_voucher(voucher_id: str):
    svc = get_svc()
    rec = svc.store.vouchers.get(voucher_id)
    if not rec:
        raise HTTPException(404, "voucher not found")
    return rec


# ---------- 覆核 ----------
@app.post("/v1/vouchers/{voucher_id}/review")
def review(voucher_id: str, body: CorrectionIn):
    state = get_svc().review(voucher_id, body.corrections,
                              reviewer=body.reviewer, approve=body.approve)
    return {"voucher_id": voucher_id, "state": state}


# ---------- 分录 ----------
@app.post("/v1/vouchers/{voucher_id}/journal-draft")
def journal_draft(voucher_id: str):
    return get_svc().draft_journal(voucher_id)


@app.post("/v1/vouchers/{voucher_id}/journal-adjust")
def journal_adjust(voucher_id: str, body: dict):
    lines = body.get("lines") or []
    return get_svc().adjust_journal(voucher_id, lines, summary=body.get("summary", ""))


@app.post("/v1/vouchers/{voucher_id}/journal-confirm")
def journal_confirm(voucher_id: str):
    return get_svc().confirm_journal(voucher_id, actor="web-user")


# ---------- 规则/发现 ----------
@app.post("/v1/rule-runs")
def rule_runs():
    return {"findings": get_svc().run_rules()}


@app.get("/v1/findings")
def findings():
    return get_svc().store.findings


@app.get("/v1/findings12")
def findings12():
    """12 条完整规则引擎结果（audit-os 语义）。"""
    return get_svc().run_rules12()


@app.post("/v1/findings/{index}/dispose")
def dispose(index: int, body: dict):
    d = (body or {}).get("disposition", "")
    return get_svc().dispose_finding(index, d, actor="web-user")


# ---------- 导出 ----------
@app.post("/v1/exports/report")
def export_report():
    path = get_svc().export_report()
    return FileResponse(path, filename=os.path.basename(path))


@app.post("/v1/exports/journal-excel")
def export_excel():
    path = get_svc().export_journal_excel()
    return FileResponse(path, filename=os.path.basename(path))


# ---------- AI 助手 ----------
@app.post("/v1/ai/explain-findings")
def ai_explain(body: dict):
    from .ai_assistant import AIAssistant, AIAssistantError
    try:
        ai = AIAssistant()
        vid = (body or {}).get("voucher_id")
        rec = get_svc().store.vouchers.get(vid)
        if not rec:
            raise AuditError("凭证不存在")
        fidx = [f for f in get_svc().store.findings
                 if f["voucher_id"] == vid]
        if not fidx:
            raise AuditError("该凭证无风险命中，无需解释")
        return ai.explain_findings(fidx, rec["voucher_json"])
    except AIAssistantError as e:
        return JSONR({"code": "ai_disabled_or_invalid", "message": str(e),
                       "details": {}, "trace_id": _tid()}, 409)


# ---------- 完整性 ----------
@app.get("/v1/integrity")
def integrity():
    return get_svc().verify_integrity()


# ---------- 拍照采集包（手机端 → 工作台）----------
@app.post("/v1/vouchers/capture-batch")
def capture_batch(body: dict):
    """接收手机端采集包：{"items": [{filename, content_b64, captured_at, note?}]}。

    手机只负责拍照与本地哈希；服务端重算 SHA-256（spec §4.2 不信客户端）。
    """
    svc = get_svc()
    ids = []
    for item in (body or {}).get("items", []):
        import base64 as b64
        raw = b64.b64decode(item.get("content_b64", ""))
        vid = svc.ingest(item.get("filename", "photo.jpg"), raw,
                          source="android_camera")
        ids.append({"voucher_id": vid, "captured_at": item.get("captured_at"),
                     "note": item.get("note", "")})
    return {"ingested": len(ids), "vouchers": ids}


# ---------- 用户自有报告上传（写作风格学习素材）----------
@app.post("/v1/reports/upload-style-sample")
def upload_style_sample(body: dict):
    """用户上传自己写过的历史审计报告（文本），进入 style_samples 库。

    仅用于 AI 助手写作风格参考；原文存本地不外发（spec §8.2）。
    """
    svc = get_svc()
    title = (body or {}).get("title") or "untitled"
    text = (body or {}).get("text", "")
    if len(text) < 50:
        return JSONR({"code": "too_short",
                       "message": "报告正文太短（<50 字符），请检查粘贴是否完整",
                       "details": {}, "trace_id": _tid()}, 400)
    sample = {"id": str(uuid.uuid4())[:8], "title": title,
               "chars": len(text), "added_at": _tid(),
               "text_head": text[:2000]}
    svc.store.style_samples.append(sample)
    svc.store.save()
    return sample


@app.get("/v1/reports/style-samples")
def list_style_samples():
    return get_svc().store.style_samples


# ---------- demo 数据 ----------
@app.post("/v1/demo/load")
def demo_load():
    ids = get_svc().load_demo_data()
    return {"voucher_ids": ids}
