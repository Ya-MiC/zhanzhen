"""角色与访问控制 —— 用户端/管理端分离的权限底座。

产品口径（docs/PRODUCT_TIERS.md）：
- 免费版（用户下载即用）：单机单租户，本地使用者自动是 admin——无登录门槛；
- 专业版（连服务器）：admin(事务所管理员)/accountant(做账员)/reviewer(复核人)
  /viewer(客户只读) 四种角色，接口按角色收口。

设计：不引入重型鉴权框架；API Key + 角色映射，够 MVP 用、可平滑升级 JWT。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

__all__ = ["Role", "Principal", "AuthError", "require_role", "load_principals",
           "ROLE_PERMISSIONS"]


class Role:
    ADMIN = "admin"          # 管理端：全部权限+用户管理+导出全部
    ACCOUNTANT = "accountant"  # 用户端专业位：上传/OCR/覆核/分录/跑规则/出报告
    REVIEWER = "reviewer"      # 复核位：覆核确认+报告签发流转
    VIEWER = "viewer"          # 客户只读：看报告与状态，不能改


# 角色 -> 允许的动作前缀（webapp 层按 action 字符串校验）
ROLE_PERMISSIONS: dict[str, set] = {
    Role.ADMIN: {"*"},
    Role.ACCOUNTANT: {"voucher.upload", "voucher.ocr", "voucher.review",
                       "journal.*", "rules.run", "report.export",
                       "ledger.import", "capture.import"},
    Role.REVIEWER: {"voucher.review", "journal.confirm", "report.export",
                     "findings.dispose", "voucher.read", "journal.read"},
    Role.VIEWER: {"voucher.read", "report.export", "findings.read"},
}


@dataclass
class Principal:
    """一个已识别的操作者。"""
    name: str
    role: str
    tenant_id: str = "default"

    def can(self, action: str) -> bool:
        allowed = ROLE_PERMISSIONS.get(self.role, set())
        if "*" in allowed:
            return True
        return action in allowed or any(
            a.endswith("*") and action.startswith(a[:-1]) for a in allowed)


class AuthError(Exception):
    """401/403 场景。"""


def require_role(principal: Optional["Principal"], action: str) -> Principal:
    if principal is None:
        # 免费版单机模式：无配置时默认本地 admin（下载即用）
        mode = os.environ.get("ZZ_AUTH_MODE", "local")
        if mode == "local":
            return Principal(name="local-admin", role=Role.ADMIN,
                              tenant_id=os.environ.get("ZZ_TENANT_ID", "default"))
        raise AuthError("未认证：本部署启用了多用户模式，请携带 API Key")
    if not principal.can(action):
        raise AuthError(f"角色 {principal.role} 无权执行 {action}")
    return principal


def load_principals() -> dict[str, Principal]:
    """从环境变量 ZZ_USERS 加载 API Key->Principal 映射。

    格式：ZZ_USERS="key1:alice:admin;key2:bob:accountant;key3:carl:viewer"
    未设置时返回空 dict => local 单机模式。
    密钥不入 Git（.env 管理）；生产建议换数据库存储+哈希。
    """
    out: dict[str, Principal] = {}
    raw = os.environ.get("ZZ_USERS", "")
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3:
            continue
        key, name, role = parts
        if role not in (Role.ADMIN, Role.ACCOUNTANT, Role.REVIEWER, Role.VIEWER):
            continue
        out[key] = Principal(name=name, role=role,
                              tenant_id=os.environ.get("ZZ_TENANT_ID", "default"))
    return out


def new_api_key() -> str:
    """管理员生成新 key 用。"""
    return "zzk_" + secrets.token_urlsafe(24)
