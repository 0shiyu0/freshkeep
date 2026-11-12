"""认证接口：配对码、密码登录、退出、改密、设备管理。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.config import settings
from app.core.errors import ApiError, conflict, not_found, unauthorized
from app.db.session import get_db
from app.models import Device
from app.schemas.auth import (
    AuthResult,
    ChangePasswordRequest,
    DeviceOut,
    LoginRequest,
    MeOut,
    PairRequest,
    SetPasswordRequest,
)
from app.schemas.common import ok
from app.services import auth as auth_svc
from app.services.auth import COOKIE_NAME

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_MAX_AGE = 60 * 60 * 24 * 365      # 一年；令牌本身不过期，可吊销


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,      # 内网 HTTP；上 TLS 后改 True（见 final-plan D4）
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _device_out(device: Device, current: bool = False) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        platform=device.platform,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        current=current,
    )


def _me_out(user, device: Device) -> MeOut:
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        has_password=bool(user.password_hash),
        device=_device_out(device, current=True),
    )


@router.post("/pair", summary="用配对码换取设备令牌")
def pair(
    request: Request,
    payload: PairRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    auth_svc.consume_pair_code(db, payload.code)
    user = auth_svc.get_owner(db)
    device, token = auth_svc.create_device(
        db,
        user,
        name=payload.device_name,
        platform=payload.platform,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )
    db.commit()

    if payload.platform == "web":
        _set_cookie(response, token)
        data = AuthResult(device=_device_out(device, True), user=_me_out(user, device))
    else:
        data = AuthResult(token=token, device=_device_out(device, True), user=_me_out(user, device))
    return ok(request, data.model_dump(mode="json"), "配对成功")


@router.post("/login", summary="账号密码登录")
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    user = auth_svc.get_owner(db)
    if not user.password_hash:
        raise ApiError(
            "PASSWORD_NOT_SET",
            "尚未设置密码。请先用配对码登录，再到「设置 → 修改密码」设置",
            409,
        )
    if payload.username.strip() != user.username:
        raise unauthorized("用户名或密码错误")
    if not auth_svc.verify_password(payload.password, user.password_hash):
        raise unauthorized("用户名或密码错误")

    device, token = auth_svc.create_device(
        db,
        user,
        name=payload.device_name,
        platform=payload.platform,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )
    db.commit()

    if payload.platform == "web":
        _set_cookie(response, token)
        data = AuthResult(device=_device_out(device, True), user=_me_out(user, device))
    else:
        data = AuthResult(token=token, device=_device_out(device, True), user=_me_out(user, device))
    return ok(request, data.model_dump(mode="json"), "登录成功")


@router.post("/logout", summary="退出当前设备（吊销令牌）")
def logout(
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    auth_svc.revoke_device(db, ctx.device)
    db.commit()
    _clear_cookie(response)
    return ok(request, {"revoked": True}, "已退出登录")


@router.get("/me", summary="当前用户与设备信息")
def me(request: Request, ctx: AuthContext = Depends(get_current)) -> dict:
    return ok(request, _me_out(ctx.user, ctx.device).model_dump(mode="json"))


@router.get("/devices", summary="已授权设备列表")
def list_devices(
    request: Request,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.execute(select(Device).order_by(Device.created_at.desc())).scalars().all()
    )
    return ok(
        request,
        {
            "items": [
                _device_out(d, current=d.id == ctx.device.id).model_dump(mode="json")
                for d in rows
            ],
            "total": len(rows),
        },
    )


@router.delete("/devices/{device_id}", summary="吊销指定设备")
def revoke(
    request: Request,
    device_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise not_found("设备不存在")
    if device.revoked_at is not None:
        raise conflict("该设备已吊销")
    auth_svc.revoke_device(db, device)
    db.commit()
    if device.id == ctx.device.id:
        # 吊销自己 = 退出登录
        return ok(request, {"revoked": True, "self": True}, "已退出当前设备")
    return ok(request, {"revoked": True, "self": False}, "已吊销设备")


@router.post("/password", summary="修改密码（需要旧密码）")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    if not ctx.user.password_hash:
        raise ApiError("PASSWORD_NOT_SET", "尚未设置密码，请先调用 /auth/password/set", 409)
    if not auth_svc.verify_password(payload.old_password, ctx.user.password_hash):
        raise ApiError("INVALID_OLD_PASSWORD", "旧密码不正确", 400)

    ctx.user.password_hash = auth_svc.hash_password(payload.new_password)
    ctx.user.updated_at = datetime.now(UTC)
    db.commit()
    return ok(request, {"updated": True}, "密码已修改")


@router.post("/password/set", summary="首次设置密码（未设置时可用）")
def set_password(
    request: Request,
    payload: SetPasswordRequest,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    if ctx.user.password_hash:
        raise conflict("密码已设置，请使用修改密码接口")
    ctx.user.password_hash = auth_svc.hash_password(payload.new_password)
    ctx.user.updated_at = datetime.now(UTC)
    db.commit()
    return ok(request, {"has_password": True}, "密码已设置")


@router.get("/policy", summary="认证策略（前端据此决定展示哪种登录方式）")
def policy(request: Request) -> dict:
    """未登录也可访问：告诉前端是否已设置密码、配对码有效期。"""
    return ok(
        request,
        {
            "pair_code_ttl_minutes": settings.pair_code_ttl_minutes,
            "cookie_name": COOKIE_NAME,
            "supports_password": True,
        },
    )
