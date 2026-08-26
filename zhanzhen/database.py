"""数据库层 —— SQLite 持久化（标准库，零依赖）。

按 action-tree docs/03 Canonical Data Model 建表：
companies / audit_projects / users / subscriptions / vouchers / journal_entries /
findings / event_log / api_keys。
设计：免费单机版开箱即用（自动建库）；专业版同一套表多租户隔离。
未来 PostgreSQL 迁移时 SQL 方言差异集中在本模块。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

__all__ = ["Database", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1

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
"""


class Database:
    """线程安全（check_same_thread=False + 单写连接）；WAL 模式。"""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        # 用户版本迁移位
        ver = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='schema_migrations'").fetchone()[0]
        if not ver:
            self.conn.execute("CREATE TABLE schema_migrations (version INTEGER, applied_at TEXT)")
            self.conn.execute("INSERT INTO schema_migrations VALUES (?,?)",
                               (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None

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

    def stats(self) -> dict:
        return {
            "companies": self.one("SELECT COUNT(*) c FROM companies")["c"],
            "projects": self.one("SELECT COUNT(*) c FROM audit_projects")["c"],
            "vouchers": self.one("SELECT COUNT(*) c FROM vouchers")["c"],
            "entries": self.one("SELECT COUNT(*) c FROM journal_entries")["c"],
            "users": self.one("SELECT COUNT(*) c FROM users")["c"],
            "subs": self.query("SELECT plan,status,COUNT(*) n FROM subscriptions GROUP BY plan,status"),
        }
