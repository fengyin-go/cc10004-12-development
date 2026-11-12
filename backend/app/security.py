"""身份认证与服务端越权拦截。

认证完全在本应用内完成：口令使用 PBKDF2-HMAC-SHA256 加盐哈希后保存在内存身份库，
登录成功签发不透明令牌（secrets.token_urlsafe），前端凭令牌访问受保护接口。

所有鉴权判定都在服务端完成，前端只负责展示；current_identity 在入口处拦截
缺失/失效令牌（401），各路由再按维护者/历任维护者/管理员身份做 403 越权拦截。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from fastapi import HTTPException, Request

_PBKDF2_ROUNDS = 120_000


def hash_password(password: str, *, salt: str | None = None) -> str:
    """生成 PBKDF2 加盐哈希，返回 salt$digest 形式的字符串。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """恒定时间比较口令与存储哈希，避免计时侧信道。"""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    ).hex()
    return hmac.compare_digest(candidate, digest)


class IdentityRegistry:
    """内存身份库：稳定身份标识、角色与口令哈希。"""

    def __init__(self) -> None:
        # identity_id 是稳定身份，登录名仅用于展示，重名标签/重名人员都靠它区分。
        self._identities: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, str] = {}  # token -> identity_id

    def register(self, identity_id: str, name: str, role: str, password: str) -> None:
        self._identities[identity_id] = {
            "identity_id": identity_id,
            "name": name,
            "role": role,
            "password": hash_password(password),
        }

    def login(self, identity_id: str, password: str) -> str | None:
        identity = self._identities.get(identity_id)
        if identity is None or not verify_password(password, identity["password"]):
            return None
        token = secrets.token_urlsafe(32)
        self._tokens[token] = identity_id
        return token

    def logout(self, token: str) -> bool:
        return self._tokens.pop(token, None) is not None

    def resolve_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        identity_id = self._tokens.get(token)
        identity = self._identities.get(identity_id or "")
        if identity is None:
            return None
        return {k: v for k, v in identity.items() if k != "password"}

    def get(self, identity_id: str) -> dict[str, Any] | None:
        identity = self._identities.get(identity_id)
        if identity is None:
            return None
        return {k: v for k, v in identity.items() if k != "password"}

    def list_identities(self) -> list[dict[str, Any]]:
        return [
            {"identity_id": item["identity_id"], "name": item["name"], "role": item["role"]}
            for item in self._identities.values()
        ]


registry = IdentityRegistry()


def current_identity(request: Request) -> dict[str, Any]:
    """从 Authorization: Bearer <token> 解析当前身份，失败直接 401。"""
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    identity = registry.resolve_token(token)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录或登录已失效，请重新完成身份验证")
    return identity
