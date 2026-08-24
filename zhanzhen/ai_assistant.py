"""AI 助手 —— LLM 只在叶子上，永远不改账。

权威守则：ENGINEERING_SPEC §8.2。
- 可以：把已确认结构化数据解释成会计语言；给科目候选；按 finding 起草问题清单。
- 不可以：改任何数据；无 evidence ref 就给"事实"；冒充签字意见。
- 每次调用留痕 model_runs（输入引用/prompt 版本/模型/响应哈希/schema 校验结果）。
- 默认关闭：未配置 ZZ_AI_* 时所有方法抛 AIAssistantError，绝不静默联网。
OpenAI 兼容端点均可（NVIDIA integrate / OpenRouter / 本地 vLLM）。
"""

from __future__ import annotations

import json
import os
import urllib.request

from .canonical import canonical_sha256

__all__ = ["AIAssistant", "AIAssistantError"]

PROMPT_VERSION = "zz-assist-v1"

# 助手输出必须满足的最小 schema（手工校验，零依赖）
RESPONSE_SCHEMA = {
    "required": ["answer"],
    "properties": {
        "answer": str,
        "account_suggestions": list,     # [{account, reason}]
        "uncertainties": list,           # 字符串列表
        "evidence_refs_required": bool,
    },
}


class AIAssistantError(Exception):
    pass


class AIAssistant:
    def __init__(self) -> None:
        self.base_url = os.environ.get("ZZ_AI_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("ZZ_AI_API_KEY", "")
        self.model = os.environ.get("ZZ_AI_MODEL", "")
        self.enabled = bool(self.base_url and self.api_key and self.model)
        self.model_runs: list[dict] = []

    # ---------- 对外 ----------
    def explain_findings(self, findings: list[dict], voucher_json: dict) -> dict:
        """解释一条风险命中。只喂已确认结构化字段与规则结论，不喂原文全文。"""
        txn = voucher_json.get("transaction") or {}
        context = {
            "voucher_type": voucher_json.get("voucher_type"),
            "date": txn.get("date"), "amount_incl_tax": txn.get("amount_incl_tax"),
            "tax_amount": txn.get("tax_amount"), "amount_excl_tax": txn.get("amount_excl_tax"),
            "document_no": txn.get("document_no"),
            "counterparty": (voucher_json.get("counterparty") or {}).get("name"),
            "findings": [{"rule_id": f["rule_id"], "severity": f["severity"],
                           "explanation": f["explanation"]} for f in findings],
            "evidence_sha256": [(voucher_json.get("document") or {}).get("sha256")],
        }
        prompt = (
            "你是审计助理。只基于给定 JSON 解释这些规则命中可能代表的业务含义与建议的核查步骤。"
            "禁止编造未提供的事实；不确定就写进 uncertainties。"
            "输出 JSON：{\"answer\": str, \"account_suggestions\": [{\"account\": str, \"reason\": str}], "
            "\"uncertainties\": [str]}。\n数据: " + json.dumps(context, ensure_ascii=False)
        )
        return self._chat(prompt, evidence_count=len(findings))

    def suggest_accounts(self, voucher_json: dict) -> dict:
        """科目候选（草稿参考）。缺金额直接拒绝——不猜。"""
        txn = voucher_json.get("transaction") or {}
        if txn.get("amount_incl_tax") is None:
            raise AIAssistantError("金额缺失，不做科目猜测（spec §8.2）")
        ctx = {"voucher_type": voucher_json.get("voucher_type"),
                "summary": txn.get("summary"), "counterparty":
                (voucher_json.get("counterparty") or {}).get("name"),
                "amounts": {k: txn.get(k) for k in
                    ("amount_excl_tax", "tax_amount", "amount_incl_tax")},
                "evidence_sha256": (voucher_json.get("document") or {}).get("sha256")}
        prompt = (
            "你是会计助理。基于以下凭证结构化字段给出借贷科目候选（中国企业会计准则科目表）。"
            "每条带 reason；不确定写 uncertainties。输出 JSON："
            "{\"answer\": str, \"account_suggestions\": [{\"account\": str, \"reason\": str}], "
            "\"uncertainties\": [str]}。\n数据: " + json.dumps(ctx, ensure_ascii=False)
        )
        return self._chat(prompt, evidence_count=1)

    @property
    def run_log(self) -> list[dict]:
        """model_runs 留痕（spec §3.2 model_runs 表的单机等价物）。"""
        return list(self.model_runs)

    # ---------- 内部 ----------
    def _validate(self, data: dict) -> tuple[bool, list[str]]:
        errs = []
        for k in RESPONSE_SCHEMA["required"]:
            if k not in data:
                errs.append(f"缺字段 {k}")
        for k, t in RESPONSE_SCHEMA["properties"].items():
            if k in data and not isinstance(data[k], t):
                errs.append(f"{k} 类型应为 {t.__name__ if hasattr(t,'__name__') else t}")
        return (not errs), errs

    def _chat(self, prompt: str, evidence_count: int) -> dict:
        if not self.enabled:
            raise AIAssistantError(
                "AI 助手未启用（默认关闭）。配置 ZZ_AI_BASE_URL / ZZ_AI_API_KEY / ZZ_AI_MODEL 后可用")
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                 "你是中国中小企业审计软件内的受约束助手。绝不修改数据、绝不出具审计意见、"
                 "没有证据引用不下事实结论。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.api_key}",
                      "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.load(resp)
        except Exception as e:
            raise AIAssistantError(f"LLM 调用失败: {e}") from e
        content = (raw.get("choices") or [{}])[0].get("message", {}).get("content", "")
        # 提取 JSON（容忍代码块包裹）
        txt = content.strip()
        if txt.startswith("```"):
            txt = txt.strip("`").lstrip("json").strip()
        start, end = txt.find("{"), txt.rfind("}")
        parsed = {}
        ok = False
        errs = ["empty_or_unparseable"]
        if start >= 0 and end > start:
            try:
                parsed = json.loads(txt[start:end + 1])
                ok, errs = self._validate(parsed)
            except json.JSONDecodeError as e:
                errs = [f"json_decode: {e}"]
        rec = {"prompt_version": PROMPT_VERSION, "model": self.model,
                "provider": self.base_url.split("//")[-1][:40],
                "response_hash": canonical_sha256({"content": content}),
                "schema_valid": ok, "schema_errors": errs,
                "evidence_count": evidence_count}
        self.model_runs.append(rec)
        if not ok:
            # spec §5.2：无法验证时降级人工覆核，不硬塞结果
            raise AIAssistantError(f"LLM 输出未通过 schema 校验({errs})——降级人工处理")
        return parsed
