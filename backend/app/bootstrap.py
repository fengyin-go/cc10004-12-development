"""身份库引导：演示账号在应用启动时注册，认证完全在本应用内闭环。

口令仅做演示用途，真实环境应替换为外部身份源或密钥管理服务。
"""
from __future__ import annotations

from app.security import registry

# (稳定身份标识, 展示名, 角色, 演示口令)
DEMO_IDENTITIES: list[tuple[str, str, str, str]] = [
    ("u_admin", "平台管理员", "admin", "admin-pass-2026"),
    ("u_maint_a", "资产维护人·林澈", "maintainer", "maint-pass-2026"),
    ("u_maint_b", "营销维护人·周岚", "maintainer", "maint-pass-2026"),
    ("u_analyst", "分析员·陈默", "analyst", "analyst-pass-2026"),
    ("u_guest", "访客·见习账号", "guest", "guest-pass-2026"),
]


def bootstrap_identities() -> None:
    for identity_id, name, role, password in DEMO_IDENTITIES:
        registry.register(identity_id, name, role, password)


bootstrap_identities()
