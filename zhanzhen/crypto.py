"""服务端加密层 —— 主口令派生密钥 + 文本加解密（可选依赖 cryptography）。

设计：
- derive_key(master_password, salt)：PBKDF2HMAC(SHA256, 200_000 轮) 派生 Fernet 密钥；
- encrypt_text / decrypt_text：Fernet 对称加密，返回/接收 UTF-8 字符串；
- cryptography 是可选依赖（pyproject `[server]` extra）：本模块懒加载，
  未安装时抛 CryptographyMissingError（可读提示），绝不影响纯 sqlite 单机模式。

salt 约定：服务端部署时生成一次随机盐并持久化（如 .env 的 ZZ_ENC_SALT）；
不传 salt 时使用模块内置默认盐，保证同库数据可解（单机版开箱即用）。
"""

from __future__ import annotations

import base64
import os

__all__ = [
    "CryptographyMissingError",
    "DEFAULT_SALT",
    "PBKDF2_ITERATIONS",
    "derive_key",
    "encrypt_text",
    "decrypt_text",
    "cryptography_available",
    "require_cryptography",
]

# 内置默认盐（非机密；生产建议显式传入随机盐）。16 字节。
DEFAULT_SALT = b"zhanzhen-enc-v1"
# PBKDF2 迭代次数（OWASP 2023+ 推荐 ≥ 600k for SHA256；此处按平台规范取 20 万轮）
PBKDF2_ITERATIONS = 200_000


class CryptographyMissingError(RuntimeError):
    """未安装可选依赖 `cryptography` 时抛出——提示安装命令。"""


def cryptography_available() -> bool:
    """cryptography 是否可导入（供测试 skipUnless 使用）。"""
    try:
        import cryptography  # noqa: F401
    except Exception:
        return False
    return True


def require_cryptography():
    """懒加载 cryptography，未安装时抛可读错误。返回 (Fernet, hashes, PBKDF2HMAC)。"""
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except Exception as exc:  # ImportError 及罕见的后端加载失败
        raise CryptographyMissingError(
            "需要可选依赖 cryptography（服务端加密）——"
            "请执行: pip install 'zhanzhen[server]' 或 pip install cryptography"
        ) from exc
    return Fernet, hashes, PBKDF2HMAC


def derive_key(master_password: str | bytes, salt: bytes | None = None) -> bytes:
    """由主口令派生 Fernet 密钥：PBKDF2HMAC(SHA256, 200k 轮, 32 字节) → urlsafe-b64。

    master_password: 服务端主口令；
    salt: 盐（None 时用 DEFAULT_SALT）；同一 (password, salt) 恒得同一密钥。
    """
    Fernet, hashes, PBKDF2HMAC = require_cryptography()
    if isinstance(master_password, str):
        master_password = master_password.encode("utf-8")
    if not isinstance(master_password, (bytes, bytearray)):
        raise TypeError("master_password 必须是 str 或 bytes")
    if salt is None:
        salt = DEFAULT_SALT
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=bytes(salt),
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(bytes(master_password)))


def encrypt_text(plaintext: str, key: bytes) -> str:
    """加密文本 → Fernet token 字符串（urlsafe base64，可直接入库 TEXT 列）。"""
    Fernet, _, _ = require_cryptography()
    if isinstance(plaintext, bytes):
        plaintext = plaintext.decode("utf-8")
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(token: str, key: bytes) -> str:
    """解密 Fernet token 字符串 → 明文。密钥错误/令牌被篡改时抛 InvalidToken。"""
    Fernet, _, _ = require_cryptography()
    if isinstance(token, bytes):
        token = token.decode("ascii", errors="replace")
    # 密钥不对时让异常信息更友好（保留原异常类型语义：InvalidToken）
    try:
        return Fernet(key).decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        exc_name = type(exc).__name__
        if "InvalidToken" in exc_name:
            raise  # 保持 cryptography.exceptions.InvalidToken 原样抛出
        raise


def random_salt(n: int = 16) -> bytes:
    """生成部署用随机盐（os.urandom）。"""
    return os.urandom(n)
