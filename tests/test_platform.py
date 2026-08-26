"""数据库/订阅/权限 三大新模块测试。"""

import os
import tempfile
import unittest

from zhanzhen.database import Database
from zhanzhen.billing import Billing


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))

    def test_schema_created(self):
        tables = {r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("companies", "audit_projects", "users", "subscriptions",
                   "vouchers", "journal_entries", "findings", "event_log",
                    "export_jobs"):
            self.assertIn(t, tables)

    def test_subscription_default_free(self):
        sub = self.db.ensure_subscription("tenant-a")
        self.assertEqual(sub["plan"], "free")
        self.assertEqual(sub["monthly_report_quota"], 3)

    def test_report_quota_consumption(self):
        self.db.ensure_subscription("t1")
        for i in range(3):
            ok, _ = self.db.check_and_consume_report_quota("t1")
            self.assertTrue(ok)
        ok, msg = self.db.check_and_consume_report_quota("t1")
        self.assertFalse(ok)
        self.assertIn("额度", msg)


class TestBilling(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(tempfile.mkdtemp(), "b.db"))
        self.b = Billing(self.db)

    def test_upgrade_to_pro_removes_limits(self):
        self.db.ensure_subscription("acme")
        plan = self.b.upgrade("acme")
        self.assertEqual(plan["plan"], "pro")
        self.assertGreater(plan["monthly_report_quota"], 1000)

    def test_downgrade_restores_free(self):
        self.b.upgrade("acme")
        plan = self.b.downgrade("acme")
        self.assertEqual(plan["plan"], "free")
        self.assertEqual(plan["monthly_report_quota"], 3)

    def test_freeze_expired_pro(self):
        import uuid
        from datetime import datetime, timedelta
        past = (datetime.utcnow() - timedelta(days=30)).isoformat()
        self.db.execute(
            "INSERT INTO subscriptions (id,tenant_id,plan,expires_at,status)"
            " VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), "dead-co", "pro", past, "active"))
        n = self.b.freeze_expired()
        self.assertGreaterEqual(n, 1)
        row = self.db.one("SELECT status FROM subscriptions WHERE tenant_id='dead-co'")
        self.assertEqual(row["status"], "frozen")


class TestAuth(unittest.TestCase):
    def test_local_mode_defaults_admin(self):
        from zhanzhen.auth import require_role, Role
        p = require_role(None, "voucher.upload")
        self.assertEqual(p.role, Role.ADMIN)

    def test_role_permissions(self):
        from zhanzhen.auth import Principal, require_role, AuthError
        viewer = Principal(name="c", role="viewer")
        with self.assertRaises(AuthError):
            require_role(viewer, "voucher.upload")   # 只读不能传
        ok = require_role(viewer, "report.export")
        self.assertEqual(ok.role, "viewer")

    def test_load_principals_from_env(self):
        os.environ["ZZ_USERS"] = "k1:alice:admin;k2:bob:accountant"
        try:
            from zhanzhen.auth import load_principals
            ps = load_principals()
            self.assertEqual(ps["k1"].role, "admin")
            self.assertEqual(ps["k2"].name, "bob")
        finally:
            del os.environ["ZZ_USERS"]


if __name__ == "__main__":
    unittest.main()
