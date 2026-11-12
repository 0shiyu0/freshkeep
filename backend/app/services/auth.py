"""认证：密码哈希、设备令牌、配对码。

设计（docs/ARCHITECTURE.md §4）：
- Web 走 HttpOnly Cookie，App 走 Authorization: Bearer，两者都映射到 devices.id
- 令牌只存 SHA-256，不落明文；吊销即失效
- 密码为可选第二通道（配对码是主通道）；未设置密码时登录接口返回 PASSWORD_NOT_SET
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.errors import ApiError
from app.models import Device, PairCode, User
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

COOKIE_NAME = "fk_sid"
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # 去掉 0/O/1/I/L
_hasher = PasswordHasher()


# ---------------------------------------------------------------- 密码


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------- 令牌


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def gen_pair_code(length: int = 6) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


# ---------------------------------------------------------------- 设备


def create_device(
    db: Session, user: User, *, name: str, platform: str, ip: str | None, ua: str | None
) -> tuple[Device, str]:
    """新建设备并返回 (device, 明文令牌)。令牌只在这里出现一次。"""
    token = new_token()
    device = Device(
        user_id=user.id,
        name=(name or "未命名设备")[:40],
        platform=platform,
        token_hash=hash_token(token),
        ip=ip,
        user_agent=(ua or "")[:300],
        last_seen_at=datetime.now(UTC),
    )
    db.add(device)
    db.flush()
    return device, token


def resolve_token(db: Session, token: str | None) -> tuple[Device, User] | None:
    if not token:
        return None
    device = db.execute(
        select(Device).where(Device.token_hash == hash_token(token), Device.revoked_at.is_(None))
    ).scalar_one_or_none()
    if device is None:
        return None
    user = db.get(User, device.user_id)
    if user is None:
        return None
    return device, user


def touch_device(db: Session, device: Device) -> None:
    """更新最后活跃时间；按分钟节流，避免每个请求都写库。"""
    now = datetime.now(UTC)
    last = device.last_seen_at
    if last is None or (now - last).total_seconds() > 60:
        device.last_seen_at = now


def revoke_device(db: Session, device: Device) -> None:
    device.revoked_at = datetime.now(UTC)


# ---------------------------------------------------------------- 配对码


def issue_pair_code(db: Session) -> str:
    code = gen_pair_code()
    db.add(
        PairCode(
            code_hash=hash_token(code),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.pair_code_ttl_minutes),
        )
    )
    return code


def consume_pair_code(db: Session, code: str) -> None:
    """校验并作废配对码；失败抛 ApiError。"""
    row = db.execute(
        select(PairCode).where(PairCode.code_hash == hash_token(code), PairCode.used_at.is_(None))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("INVALID_PAIR_CODE", "配对码无效或已使用", 401)
    if row.expires_at < datetime.now(UTC):
        raise ApiError("PAIR_CODE_EXPIRED", "配对码已过期，请在服务器上重新生成", 401)
    row.used_at = datetime.now(UTC)


# ---------------------------------------------------------------- 用户


def get_owner(db: Session) -> User:
    """单用户系统：取第一个用户，不存在则创建。"""
    user = db.execute(select(User).order_by(User.created_at)).scalars().first()
    if user is None:
        user = User(username="owner", display_name="主人")
        db.add(user)
        db.flush()
    return user
