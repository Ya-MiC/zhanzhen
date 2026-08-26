"""平台 v2 测试：服务端加密 + 数据库双后端（PostgreSQL/SQLite）。

覆盖：加密往返 / 错钥失败 / 报告资产加密落库 / sqlite 降级 /
占位符翻译 / 订阅额度不回归。
cryptography 为可选依赖——未安装时相关用例 skip（其余仍跑）。
"""

import os
import tempfile
import unittest
from unittest import mock

from zhanzhen.crypto import (
    CryptographyMissingError,
    PBKDF2_ITERATIONS,
    cryptography_available,
    decrypt_text,
    derive_key,
    encrypt_text,
)
from zhanzhen.database import Database, DatabaseBackendError
from zhanzhen.billing import Billing

CRYPTO = cryptography_available()
SALT = b"unit-test-salt-16b"


def _fresh_db() -> Database:
    """强制 sqlite 路径（清掉可能存在的 ZZ_DATABASE_URL）。"""
    env = os.environ.pop("ZZ_DATABASE_URL", None)
    try:
        return Database(os.path.join(tempfile.mkdtemp(), "t.db"))
    finally:
        if env is not None:
            os.environ["ZZ_DATABASE_URL"] = env


@unittest.skipUnless(CRYPTO, "可选依赖 cryptography 未安装")
class TestCrypto(unittest.TestCase):
    def test_derive_key_deterministic_pbkdf2(self):
        k1 = derive_key("master-pw", SALT)
        k2 = derive_key(b"master-pw", SALT)
        self.assertEqual(k1, k2)                      # 同 (口令, 盐) → 同密钥
        self.assertNotEqual(derive_key("other", SALT), k1)
        self.assertEqual(PBKDF2_ITERATIONS, 200_000)  # 规范要求 20 万轮

    def test_encrypt_decrypt_roundtrip(self):
        key = derive_key("pw-中文", SALT)
        for text in ("审计报告正文：营业收入 1,234.56 元",
                     "line\nbreaks\tand emoji ✅", ""):
            token = encrypt_text(text, key)
            self.assertIsInstance(token, str)
            if text:
                self.assertNotIn(text, token)         # 库里不落明文
            self.assertEqual(decrypt_text(token, key), text)

    def test_wrong_key_fails(self):
        key = derive_key("right-password", SALT)
        wrong = derive_key("wrong-password", SALT)
        token = encrypt_text("机密正文", key)
        with self.assertRaises(Exception) as ctx:
            decrypt_text(token, wrong)
        self.assertIn("InvalidToken", type(ctx.exception).__name__)
        # 换盐同样不可解
        other_salt_key = derive_key("right-password", b"another-salt-16byte")
        with self.assertRaises(Exception):
            decrypt_text(token, other_salt_key)


@unittest.skipUnless(CRYPTO, "可选依赖 cryptography 未安装")
class TestReportAssets(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.addCleanup(self.db.close)
        self.key = derive_key("server-master", SALT)

    def test_save_encrypted_at_rest_and_get_roundtrip(self):
        asset = self.db.save_report_asset(
            "tenant-a", "2025年度审计报告",
            body="报告正文（机密）：收入 8,000 万",
            style="正式蓝白模板", audience="董事会",
            created_by="alice", key=self.key)
        # 元数据明文、正文密文
        raw = self.db.one("SELECT * FROM report_assets WHERE id=?",
                          (asset["id"],))
        self.assertIsNotNone(raw)
        self.assertEqual(raw["title"], "2025年度审计报告")
        self.assertNotEqual(raw["body_encrypted"], "报告正文（机密）：收入 8,000 万")
        self.assertNotEqual(raw["style_encrypted"], "正式蓝白模板")
        for col in ("id", "tenant_id", "title", "audience",
                    "body_encrypted", "style_encrypted",
                    "created_by", "created_at"):
            self.assertIn(col, raw)                   # 规范要求的全部列
        out = self.db.get_report_asset(asset["id"], "tenant-a", key=self.key)
        self.assertEqual(out["body"], "报告正文（机密）：收入 8,000 万")
        self.assertEqual(out["style"], "正式蓝白模板")
        self.assertEqual(out["created_by"], "alice")

    def test_wrong_master_password_cannot_decrypt(self):
        asset = self.db.save_report_asset(
            "t1", "r", body="secret-body", style="s",
            master_password="correct-horse")
        with self.assertRaises(ValueError):
            self.db.get_report_asset(asset["id"], "t1",
                                     master_password="battery-staple")

    def test_list_returns_metadata_without_plaintext(self):
        self.db.save_report_asset("t9", "A", body="ba", style="sa", key=self.key)
        self.db.save_report_asset("t9", "B", body="bb", key=self.key)
        rows = self.db.list_report_assets("t9")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all({"id", "title"} <= set(r) for r in rows))
        self.assertFalse(any("body" in r or "body_encrypted" in r for r in rows))

    def test_crypto_missing_raises_readable_error(self):
        import builtins
        from zhanzhen import crypto
        self.assertIsNotNone(crypto.DEFAULT_SALT)
        # 模拟"未安装 cryptography"：拦截 __import__
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cryptography" or name.startswith("cryptography."):
                raise ImportError(f"No module named '{name}' (simulated missing)")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(CryptographyMissingError) as ctx:
                crypto.derive_key("pw", SALT)
            self.assertIn("pip install", str(ctx.exception))  # 可读安装提示
            with self.assertRaises(CryptographyMissingError):
                crypto.encrypt_text("x", b"k")


class TestDualBackend(unittest.TestCase):
    def test_sqlite_fallback_when_no_env(self):
        removed = os.environ.pop("ZZ_DATABASE_URL", None)
        try:
            db = Database(os.path.join(tempfile.mkdtemp(), "fb.db"))
            self.addCleanup(db.close)
            self.assertEqual(db.backend, "sqlite")
            db.execute("INSERT INTO companies (id,name) VALUES (?,?)", ("c1", "甲公司"))
            row = db.one("SELECT name FROM companies WHERE id=?", ("c1",))
            self.assertEqual(row["name"], "甲公司")   # 降级后全功能可用
        finally:
            if removed is not None:
                os.environ["ZZ_DATABASE_URL"] = removed

    def test_env_dsn_selects_postgres_backend_lazy_import_error(self):
        try:
            psycopg2_ok = True
            try:
                import psycopg2  # noqa: F401
            except Exception:
                psycopg2_ok = False
            if psycopg2_ok:
                self.skipTest("psycopg2 已安装——仅验证未装时的可读错误路径")
            with mock.patch.dict(os.environ, {"ZZ_DATABASE_URL":
                                              "postgresql://u:p@127.0.0.1:5/db"}):
                with self.assertRaises(DatabaseBackendError) as ctx:
                    Database(os.path.join(tempfile.mkdtemp(), "x.db"))
                self.assertIn("psycopg2", str(ctx.exception))
        finally:
            os.environ.pop("ZZ_DATABASE_URL", None)

    def test_translate_placeholders(self):
        db = _fresh_db()
        self.addCleanup(db.close)
        sql = "SELECT * FROM t WHERE a=? AND b LIKE '%?%' AND c=?"
        self.assertEqual(
            db._translate_placeholders(sql, backend="sqlite"), sql)   # sqlite 原样
        pg = db._translate_placeholders(sql, backend="postgres")
        self.assertEqual(pg, "SELECT * FROM t WHERE a=%s AND b LIKE '%%?%%' AND c=%s")
        # 引号内的 ? 不翻译；裸 % 转义为 %%
        self.assertEqual(db._translate_placeholders("UPDATE t SET s='50%' WHERE id=?",
                                                    backend="postgres"),
                         "UPDATE t SET s='50%%' WHERE id=%s")
        # 实际执行走同一适配层（sqlite 后端 ? 直接可用）
        db.execute("INSERT INTO companies (id,name) VALUES (?,?)", ("cx", "乙"))
        self.assertEqual(db.one("SELECT COUNT(*) c FROM companies WHERE id=?",
                                ("cx",))["c"], 1)

    def test_schema_v2_recorded_and_report_assets_table_exists(self):
        db = _fresh_db()
        self.addCleanup(db.close)
        tables = {r["name"] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("report_assets", tables)
        ver = db.one("SELECT MAX(version) v FROM schema_migrations")["v"]
        self.assertGreaterEqual(ver, 2)


class TestQuotaNoRegression(unittest.TestCase):
    """双后端改造后订阅额度行为不变。"""

    def test_free_quota_3_per_month_still_enforced(self):
        db = _fresh_db()
        self.addCleanup(db.close)
        db.ensure_subscription("tq")
        for _ in range(3):
            ok, _msg = db.check_and_consume_report_quota("tq")
            self.assertTrue(ok)
        ok, msg = db.check_and_consume_report_quota("tq")
        self.assertFalse(ok)
        self.assertIn("额度", msg)

    def test_pro_upgrade_unlimited_and_billing_lifecycle(self):
        db = _fresh_db()
        self.addCleanup(db.close)
        b = Billing(db)
        plan = b.upgrade("tq-pro")
        self.assertEqual(plan["plan"], "pro")
        self.assertGreater(plan["monthly_report_quota"], 1000)
        ok, _ = db.check_and_consume_report_quota("tq-pro")
        self.assertTrue(ok)
        plan = b.downgrade("tq-pro")
        self.assertEqual(plan["plan"], "free")
        self.assertEqual(plan["monthly_report_quota"], 3)


if __name__ == "__main__":
    unittest.main()
