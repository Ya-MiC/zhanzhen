"""数据库层 —— 双后端持久化：PostgreSQL（ZZ_DATABASE_URL）或 SQLite（默认，零依赖）。

按 action-tree docs/03 Canonical Data Model 建表：
companies / audit_projects / users / subscriptions / vouchers / journal_entries /
findings / event_log / api_keys / report_assets。
设计：免费单机版开箱即用（自动建 SQLite 库）；专业版设 ZZ_DATABASE_URL 即切
PostgreSQL 多租户部署，同一套 SQL。

方言适配：
- 统一以 `?` 作为参数占位符书写 SQL；Database.execute/query/one 内部经
  _translate_placeholders 翻译成目标后端占位符（sqlite=? / postgres=%s，
  并把裸 `%` 转义为 `%%` 以适配 psycopg2）；
- psycopg2 懒加载：未安装时报可读错误（pyproject `[server]` extra 提供）；
- 建表语句集中在本模块，AUTOINCREMENT/datetime('now') 等差异在初始化时翻译。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = ["Database", "SCHEMA_VERSION"]

SCHEMA_VERSION = 2

_SQLITE_BACKEND = "sqlite"
_PG_BACKEND = "postgres"
_PG_SCHEMES = ("postgres://", "postgresql://")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  name TEXT NOT NULL,
  uscc TEXT,
  industry_code TEXT,
  scale TEXT CHECK(scale IN ('micro','small','medium')) DEFAULT 'small',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_projects (
  id TEXT PRIMARY KEY,
  company_id TEXT REFERENCES companies(id),
  tenant_id TEXT NOT NULL,
  period_start TEXT, period_end TEXT,
  report_type TEXT CHECK(report_type IN ('annual','special','due_diligence','cross_border')) DEFAULT 'annual',
  status TEXT CHECK(status IN ('init','ingested','analyzed','reported','archived')) DEFAULT 'init',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT UNIQUE NOT NULL,
  role TEXT CHECK(role IN ('admin','accountant','reviewer','viewer')) NOT NULL,
  api_key_hash TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT UNIQUE NOT NULL,
  plan TEXT CHECK(plan IN ('free','pro')) NOT NULL DEFAULT 'free',
  monthly_report_quota INTEGER NOT NULL DEFAULT 3,     -- 免费:3份/月
  reports_used_this_month INTEGER NOT NULL DEFAULT 0,
  quota_period TEXT,                                    -- 'YYYY-MM'
  ocr_quota_monthly INTEGER NOT NULL DEFAULT 100,
  ocr_used_this_month INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  status TEXT CHECK(status IN ('active','grace','frozen')) DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vouchers (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT REFERENCES audit_projects(id),
  state TEXT NOT NULL,                    -- 状态机12态
  voucher_json TEXT NOT NULL,             -- VoucherJSON v1 序列化
  filename TEXT,
  entry_id TEXT,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_vouchers_tenant_state ON vouchers(tenant_id, state);

CREATE TABLE IF NOT EXISTS journal_entries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  voucher_id TEXT REFERENCES vouchers(id),
  status TEXT CHECK(status IN ('draft','confirmed','reversed')) NOT NULL,
  summary TEXT,
  lines_json TEXT NOT NULL,
  lines_hash TEXT NOT NULL,
  reversal_of TEXT,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  engine TEXT CHECK(engine IN ('mvp','rules12')) NOT NULL DEFAULT 'mvp',
  rule_id TEXT NOT NULL,
  severity TEXT,
  voucher_ref TEXT,
  payload_json TEXT NOT NULL,
  disposition TEXT DEFAULT 'open',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  actor_type TEXT,
  actor_id TEXT,
  payload_json TEXT,
  previous_event_hash TEXT,
  event_hash TEXT NOT NULL,
  UNIQUE(aggregate_id, sequence)
);

CREATE TABLE IF NOT EXISTS export_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  audience TEXT,
  template_version TEXT,
  path TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 报告资产（服务端加密）：body 与 style 加密后入库，库中不落明文
CREATE TABLE IF NOT EXISTS report_assets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  title TEXT NOT NULL,
  audience TEXT,
  body_encrypted TEXT NOT NULL,
  style_encrypted TEXT,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_report_assets_tenant ON report_assets(tenant_id, created_at);
"""


class DatabaseBackendError(RuntimeError):
    """数据库后端不可用/依赖缺失——带安装提示的可读错误。"""


class Database:
    """双后端连接封装。

    - ZZ_DATABASE_URL 有值 → PostgreSQL(psycopg2，懒加载)；
    - 否则 → SQLite(path)。
    path 参数也可直接传 postgres(dsn) 字符串强制指定后端。
    所有业务 SQL 用 `?` 占位符书写，由 _translate_placeholders 适配后端。
    """

    backend: str

    def __init__(self, path: Optional[str] = None) -> None:
        dsn = self._resolve_dsn(path)
        if dsn:
            self.backend = _PG_BACKEND
            self.dsn = dsn
            self.path = None
            self.conn = self._connect_postgres(dsn)
        else:
            self.backend = _SQLITE_BACKEND
            self.path = path or os.environ.get("ZZ_DB_PATH", "data/zhanzhen.db")
            parent = os.path.dirname(self.path) or "."
            os.makedirs(parent, exist_ok=True)
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ---- 后端解析 / 连接 ----
    @staticmethod
    def _resolve_dsn(path: Optional[str]) -> str:
        """显式 DSN 参数优先；其次 ZZ_DATABASE_URL 环境变量；否则空（sqlite）。"""
        if path and str(path).startswith(_PG_SCHEMES):
            return str(path)
        env = (os.environ.get("ZZ_DATABASE_URL") or "").strip()
        return env if env else ""

    @staticmethod
    def _import_psycopg2():
        try:
            import psycopg2  # 可选依赖：zhanzhen[server]
        except Exception as exc:
            raise DatabaseBackendError(
                "需要可选依赖 psycopg2（PostgreSQL 后端）——"
                "请执行: pip install 'zhanzhen[server]' 或 pip install psycopg2-binary；"
                "或取消设置 ZZ_DATABASE_URL 以回退 SQLite。"
            ) from exc
        return psycopg2

    @classmethod
    def _connect_postgres(cls, dsn: str):
        psycopg2 = cls._import_psycopg2()
        try:
            conn = psycopg2.connect(dsn)
        except Exception as exc:
            raise DatabaseBackendError(
                f"无法连接 ZZ_DATABASE_URL 指定的 PostgreSQL（{type(exc).__name__}: {exc}）；"
                "或取消设置 ZZ_DATABASE_URL 以回退 SQLite。"
            ) from exc
        conn.autocommit = False
        return conn

    @staticmethod
    def _to_postgres_schema(schema_sql: str) -> str:
        """SQLite 风格建表脚本 → PostgreSQL 兼容脚本。"""
        out = schema_sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                 "BIGSERIAL PRIMARY KEY")
        out = out.replace("DEFAULT (datetime('now'))", "DEFAULT CURRENT_TIMESTAMP")
        return out

    def _run_schema(self, schema_sql: str) -> None:
        if self.backend == _SQLITE_BACKEND:
            self.conn.executescript(schema_sql)
            return
        for stmt in self._translate_placeholders(
                self._to_postgres_schema(schema_sql), backend=_PG_BACKEND).split(";"):
            stmt = stmt.strip()
            if stmt:
                cur = self.conn.cursor()
                cur.execute(stmt)
        self.conn.commit()

    def _init_schema(self) -> None:
        self._run_schema(_SCHEMA)
        # 用户版本迁移位（两后端同构）
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version INTEGER, applied_at TEXT)")
        n = self.one("SELECT COUNT(*) AS c FROM schema_migrations")["c"]
        now_iso = datetime.now(timezone.utc).isoformat()
        if not n:
            self.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?,?)",
                         (SCHEMA_VERSION, now_iso))
            return
        ver = self.one("SELECT MAX(version) AS v FROM schema_migrations")["v"] or 0
        if ver < SCHEMA_VERSION:
            self.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?,?)",
                         (SCHEMA_VERSION, now_iso))

    # ---- 资源管理 ----
    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # ---- 占位符适配 ----
    @staticmethod
    def _swap_qmark(sql: str) -> str:
        """`?`→`%s`（字符串字面量内的 ? 不算占位符），并把裸 `%`→`%%`。

        注意：psycopg2 对整条 SQL 做参数插值，因此字面量里的裸 % 也必须转义
        （插值时 %% 还原为 %），否则含 LIKE '%…%' 的语句在 PG 后端会报错。
        """
        out: list[str] = []
        in_str = False
        i = 0
        while i < len(sql):
            ch = sql[i]
            if in_str:
                if ch == "%":
                    out.append("%%")
                else:
                    out.append(ch)
                if ch == "'":
                    if i + 1 < len(sql) and sql[i + 1] == "'":   # '' 转义引号
                        out.append("'")
                        i += 1
                    else:
                        in_str = False
            elif ch == "'":
                in_str = True
                out.append(ch)
            elif ch == "?":
                out.append("%s")
            elif ch == "%":
                out.append("%%")
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    def _translate_placeholders(self, sql: str, backend: Optional[str] = None) -> str:
        """把统一书写的 `?` 占位符翻译为目标后端占位符。

        sqlite → 原样返回；postgres → %s（并转义字面 %）。
        """
        target = backend or self.backend
        return sql if target == _SQLITE_BACKEND else self._swap_qmark(sql)

    # ---- 基础执行 ----
    def execute(self, sql: str, params: tuple = ()) -> Any:
        cur = self.conn.cursor()
        cur.execute(self._translate_placeholders(sql), params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(self._translate_placeholders(sql), params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- 订阅额度 ----
    def ensure_subscription(self, tenant_id: str, plan: str = "free") -> dict:
        row = self.one("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,))
        if row:
            return row
        quota = 9999 if plan == "pro" else 3
        ocr_q = 9999 if plan == "pro" else 100
        now = datetime.now(timezone.utc)
        import uuid
        self.execute(
            "INSERT INTO subscriptions (id,tenant_id,plan,monthly_report_quota,"
            "quota_period,ocr_quota_monthly,status) VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), tenant_id, plan, quota,
             now.strftime("%Y-%m"), ocr_q, "active"))
        return self.ensure_subscription(tenant_id, plan)

    def check_and_consume_report_quota(self, tenant_id: str) -> tuple[bool, str]:
        sub = self.ensure_subscription(tenant_id)
        if sub["status"] == "frozen":
            return False, "订阅已冻结——请到管理端续费"
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        if sub["quota_period"] != period:   # 新月份重置
            self.execute("UPDATE subscriptions SET reports_used_this_month=0,"
                         "ocr_used_this_month=0, quota_period=? WHERE tenant_id=?",
                          (period, tenant_id))
            sub = self.ensure_subscription(tenant_id)
        if sub["reports_used_this_month"] >= sub["monthly_report_quota"]:
            return False, "本月报告额度已用完（免费版 3 份/月）——升级专业版不限量"
        self.execute("UPDATE subscriptions SET reports_used_this_month="
                     "reports_used_this_month+1 WHERE tenant_id=?", (tenant_id,))
        return True, "ok"

    # ---- 报告资产存取层（body/style 先 encrypt_text 再落库） ----
    def _report_asset_key(self, key=None, master_password=None):
        from .crypto import CryptographyMissingError, derive_key
        if key is not None:
            return key
        if master_password:
            return derive_key(master_password)
        raise ValueError("save/get report_asset 需要 key(Fernet bytes) 或 master_password")

    def save_report_asset(self, tenant_id: str, title: str, body: str,
                          style: str = "", audience: str = "",
                          created_by: str = "", *,
                          key: Optional[bytes] = None,
                          master_password: Optional[str] = None) -> dict:
        """新建报告资产：入库前对 body/style 做 encrypt_text，库里不落明文。

        key 与 master_password 二选一；cryptography 未安装时抛可读错误。
        返回落库后的元数据行（不含明文）。
        """
        import uuid
        from .crypto import encrypt_text
        enc_key = self._report_asset_key(key, master_password)
        asset_id = str(uuid.uuid4())
        self.execute(
            "INSERT INTO report_assets (id,tenant_id,title,audience,"
            "body_encrypted,style_encrypted,created_by) VALUES (?,?,?,?,?,?,?)",
            (asset_id, tenant_id, title, audience,
             encrypt_text(body, enc_key),
             encrypt_text(style, enc_key) if style else "",
             created_by))
        return self.get_report_asset(asset_id, tenant_id,
                                     raise_if_missing=True, decrypt=False)

    def get_report_asset(self, asset_id: str, tenant_id: str, *,
                         key: Optional[bytes] = None,
                         master_password: Optional[str] = None,
                         decrypt: bool = True,
                         raise_if_missing: bool = False) -> Optional[dict]:
        """读取报告资产；decrypt=True 时用密钥解出 body/style 明文字段。"""
        row = self.one("SELECT * FROM report_assets WHERE id=? AND tenant_id=?",
                       (asset_id, tenant_id))
        if row is None:
            if raise_if_missing:
                raise KeyError(f"report_asset 不存在: {asset_id}")
            return None
        if not decrypt:
            return row
        from .crypto import decrypt_text
        enc_key = self._report_asset_key(key, master_password)
        out = {k: v for k, v in row.items() if not k.endswith("_encrypted")}
        try:
            out["body"] = decrypt_text(row["body_encrypted"], enc_key)
            out["style"] = decrypt_text(row["style_encrypted"], enc_key) \
                if row.get("style_encrypted") else ""
        except Exception as exc:
            name = type(exc).__name__
            if "InvalidToken" in name:
                raise ValueError("解密失败：主口令/密钥不匹配（InvalidToken）") from exc
            raise
        return out

    def list_report_assets(self, tenant_id: str, limit: int = 50) -> list[dict]:
        """租户内报告资产清单（仅元数据，不解密）。"""
        return self.query(
            "SELECT id,title,audience,created_by,created_at FROM report_assets "
            "WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?", (tenant_id, limit))

    # ---- 平台统计 ----
    def stats(self) -> dict:
        return {
            "companies": self.one("SELECT COUNT(*) c FROM companies")["c"],
            "projects": self.one("SELECT COUNT(*) c FROM audit_projects")["c"],
            "vouchers": self.one("SELECT COUNT(*) c FROM vouchers")["c"],
            "entries": self.one("SELECT COUNT(*) c FROM journal_entries")["c"],
            "users": self.one("SELECT COUNT(*) c FROM users")["c"],
            "subs": self.query("SELECT plan,status,COUNT(*) n FROM subscriptions GROUP BY plan,status"),
        }
