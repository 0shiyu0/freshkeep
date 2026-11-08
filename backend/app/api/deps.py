"""FastAPI 依赖：当前设备与用户。

凭据来源（docs/ARCHITECTURE.md §4）：
1. `Authorization: Bearer <token>`（原生 App）
2. `Cookie: fk_sid=<token>`（Web，HttpOnly）
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import unauthorized
from app.db.session import get_db
from app.models import Device, User
from app.services.auth import COOKIE_NAME, resolve_token, touch_device


@dataclass
class AuthContext:
    device: Device
    user: User


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


def get_current(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    """解析凭据；失败抛 401（前端拦截器统一跳登录）。"""
    token = _extract_token(request)
    resolved = resolve_token(db, token)
    if resolved is None:
        raise unauthorized("未登录或登录已失效")
    device, user = resolved
    touch_device(db, device)
    db.commit()
    return AuthContext(device=device, user=user)


def get_optional(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    """可选认证：用于 /ping 这类既想公开又想识别设备的接口。"""
    token = _extract_token(request)
    resolved = resolve_token(db, token)
    if resolved is None:
        return None
    device, user = resolved
    touch_device(db, device)
    return AuthContext(device=device, user=user)
