"""内容寻址对象存储（本地目录实现）。

spec §4.2：server 端重算 SHA-256，不信客户端；原始文件只读；
对象 key = objects/<sha256 前2位>/<sha256>。未来换 MinIO/S3 只改本模块。
"""

from __future__ import annotations

import os

from .canonical import sha256_hex


class ObjectStore:
    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(os.path.join(root, "objects"), exist_ok=True)

    def put(self, content: bytes) -> str:
        """写入并返回 SHA-256（内容寻址：同内容天然去重）。"""
        sha = sha256_hex(content)
        d = os.path.join(self.root, "objects", sha[:2])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sha)
        if not os.path.exists(path):          # 只读语义：存在即不覆盖
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(content)
            os.replace(tmp, path)
        return sha

    def get(self, sha256: str) -> bytes:
        with open(os.path.join(self.root, "objects", sha256[:2], sha256), "rb") as f:
            return f.read()

    def has(self, sha256: str) -> bool:
        return os.path.exists(os.path.join(self.root, "objects", sha256[:2], sha256))
