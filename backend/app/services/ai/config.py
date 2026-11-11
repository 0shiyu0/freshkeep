"""AI 辅助配置：全部从 `app_settings` 读，不硬编码任何地址或密钥。

两个键：
- `ai.provider`：视觉识别配置（kind=stub|openai_compatible, base_url, api_key, model, enabled）
- `product_source`：外部商品数据源（kind=none|openfoodfacts|custom, base_url, api_key, enabled）

未配置时识别接口**不报错**，而是创建空白草稿并附 `AI_NOT_CONFIGURED` 提示，
保证「AI 不可用不阻塞人工录入」。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

AI_KEY = "ai.provider"
PRODUCT_KEY = "product_source"

DEFAULT_AI = {
    "kind": "none",       # none | stub | openai_compatible
    "base_url": "",
    "api_key": "",
    "model": "",
    "enabled": False,
    "timeout_seconds": 30,
}
DEFAULT_PRODUCT = {
    "kind": "none",       # none | openfoodfacts | custom
    "base_url": "",
    "api_key": "",
    "enabled": False,
    "timeout_seconds": 8,
}


def _read(db: Session, key: str, default: dict) -> dict:
    import json

    row = db.execute(
        text("SELECT value_json FROM app_settings WHERE key = :k"), {"k": key}
    ).first()
    if row is None:
        return dict(default)
    value = row[0]
    if isinstance(value, str):
        value = json.loads(value)
    return {**default, **(value or {})}


def read_ai(db: Session) -> dict:
    return _read(db, AI_KEY, DEFAULT_AI)


def read_product_source(db: Session) -> dict:
    return _read(db, PRODUCT_KEY, DEFAULT_PRODUCT)


def write_setting(db: Session, key: str, value: dict) -> None:
    import json

    db.execute(
        text(
            "INSERT INTO app_settings (key, value_json, updated_at) "
            "VALUES (:k, CAST(:v AS jsonb), now()) "
            "ON CONFLICT (key) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = now()"
        ),
        {"k": key, "v": json.dumps(value, ensure_ascii=False)},
    )


def mask(secret: str) -> str:
    """配置回显时只显示末 4 位，避免把密钥原样吐给前端。"""
    if not secret:
        return ""
    return "*" * max(0, len(secret) - 4) + secret[-4:]
