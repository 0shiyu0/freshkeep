"""认证相关模型：配对码、密码登录、改密、设备。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMBase


class PairRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    device_name: str = Field(default="未命名设备", max_length=40)
    platform: str = Field(default="web", pattern="^(web|ios|android)$")

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="网页", max_length=40)
    platform: str = Field(default="web", pattern="^(web|ios|android)$")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _same(self):
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if self.new_password == self.old_password:
            raise ValueError("新密码不能与旧密码相同")
        return self


class SetPasswordRequest(BaseModel):
    """首次设置密码（尚未设置时允许，无需旧密码）。"""

    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _same(self):
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        return self


class DeviceOut(ORMBase):
    id: uuid.UUID
    name: str
    platform: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    current: bool = False


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    has_password: bool
    device: DeviceOut


class AuthResult(BaseModel):
    token: str | None = None      # 仅原生 App 返回；Web 走 HttpOnly Cookie
    device: DeviceOut
    user: MeOut
