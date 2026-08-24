"""Canonical JSON 序列化与 SHA-256 —— 全服务唯一实现。

权威定义：action-tree/specs/events-v1.md「Canonical JSON 規則」：
1. 鍵按 UTF-8 位元組序遞迴排序；
2. 無空白分隔符；
3. 數字用最短無歧義表示（int 原樣；float 用最短往返表示，禁 NaN/Infinity）；
4. event_hash = SHA256(canonical_json(event 去掉 event_hash 欄位))。

本模塊是唯一實現；任何其他服務不得自行實現排序規則（以本文件測試固定）。
標準庫實現，零第三方依賴。
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

__all__ = ["canonical_json", "canonical_bytes", "canonical_sha256", "sha256_hex"]


def _canon(obj: Any) -> str:
    """遞迴產生 canonical JSON 字符串。"""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        # json.dumps 的字符串轉義即 RFC 8259 最短形式
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("NaN/Infinity 不可進入 canonical JSON")
        if obj.is_integer() and abs(obj) < 1e15:
            # 5.0 -> "5.0"：保留浮點語義，避免與 int 5 哈希撞車
            return repr(obj)
        return repr(obj)  # Python repr 即最短往返表示
    if isinstance(obj, Decimal):
        # 金額統一走 Decimal 時的確定性表示
        if not obj.is_finite():
            raise ValueError("非有限 Decimal 不可序列化")
        s = format(obj.normalize(), "f")
        return s
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0].encode("utf-8"))
        return "{" + ",".join(
            json.dumps(str(k), ensure_ascii=False) + ":" + _canon(v) for k, v in items
        ) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_canon(x) for x in obj) + "]"
    raise TypeError(f"不可序列化類型: {type(obj)!r}")


def canonical_json(obj: Any) -> str:
    """返回 canonical JSON 字符串。"""
    return _canon(obj)


def canonical_bytes(obj: Any) -> bytes:
    """返回 UTF-8 編碼字節，供哈希使用。"""
    return canonical_json(obj).encode("utf-8")


def canonical_sha256(obj: Any) -> str:
    """SHA256(canonical_json(obj))，十六進制小寫。"""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_hex(data: bytes) -> str:
    """原始字節的 SHA-256（檔案完整性用）。"""
    return hashlib.sha256(data).hexdigest()
