"""订阅计费 —— 免费/专业两档（创始人定稿：不做多档）。

免费版：下载即用，本地 admin，每月 3 份报告 + 100 张 OCR
专业版：不限量额度 + PDF/docx 模板 + 云同步（¥199/年，见 PRODUCT_TIERS）
到期处理：宽限7天只读 → 冻结（数据保留90天）→ 用户可随时导出
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["Billing"]


class Billing:
    PLAN_LIMITS = {
        "free": {"reports": 3, "ocr": 100},
        "pro": {"reports": 9999, "ocr": 9999},
    }

    def __init__(self, db) -> None:
        self.db = db   # zhanzhen.database.Database

    def current_plan(self, tenant_id: str) -> dict:
        return self.db.ensure_subscription(tenant_id)

    def upgrade(self, tenant_id: str, months: int = 12) -> dict:
        """升级专业版（支付回调后调用；MVP 阶段管理端手动开通）。"""
        import uuid
        expires = (datetime.now(timezone.utc)
                    + timedelta(days=30 * months)).isoformat()
        self.db.ensure_subscription(tenant_id, "pro")
        self.db.execute(
            "UPDATE subscriptions SET plan='pro', status='active',"
            " monthly_report_quota=?, ocr_quota_monthly=?, expires_at=?"
            " WHERE tenant_id=?",
            (self.PLAN_LIMITS["pro"]["reports"],
             self.PLAN_LIMITS["pro"]["ocr"], expires, tenant_id))
        return self.current_plan(tenant_id)

    def downgrade(self, tenant_id: str) -> dict:
        self.db.execute(
            "UPDATE subscriptions SET plan='free', monthly_report_quota=3,"
            " ocr_quota_monthly=100, expires_at=NULL WHERE tenant_id=?",
            (tenant_id,))
        return self.current_plan(tenant_id)

    def freeze_expired(self) -> int:
        """到期冻结：expires_at 过了宽限期(7天)的 pro → frozen。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cur = self.db.execute(
            "UPDATE subscriptions SET status='frozen' WHERE plan='pro'"
            " AND status='active' AND expires_at IS NOT NULL AND expires_at < ?",
            (cutoff,))
        return cur.rowcount

    def consume_report(self, tenant_id: str) -> tuple[bool, str]:
        ok, msg = self.db.check_and_consume_report_quota(tenant_id)
        return ok, msg

    def consume_ocr(self, tenant_id: str, n: int = 1) -> tuple[bool, str]:
        sub = self.db.ensure_subscription(tenant_id)
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        if sub["quota_period"] != period:
            self.db.execute("UPDATE subscriptions SET reports_used_this_month=0,"
                             "ocr_used_this_month=0, quota_period=? WHERE tenant_id=?",
                              (period, tenant_id))
            sub = self.db.ensure_subscription(tenant_id)
        if sub["ocr_used_this_month"] + n > sub["ocr_quota_monthly"]:
            return False, f"本月 OCR 额度不足（剩 {sub['ocr_quota_monthly']-sub['ocr_used_this_month']} 张）"
        self.db.execute("UPDATE subscriptions SET ocr_used_this_month="
                         "ocr_used_this_month+? WHERE tenant_id=?", (n, tenant_id))
        return True, "ok"
