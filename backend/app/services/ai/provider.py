"""视觉识别 provider：可插拔，默认关闭；任何失败都不影响库存。

- `stub`：离线固定输出，供开发与自动化测试（provider 会如实标记为 stub）；
- `openai_compatible`：POST `{base_url}/chat/completions`，把图片以 data URL 传入，
  要求模型返回 JSON（name / brand / specification / barcode / nutrition / dates）。
- `none`：未配置，上层创建空白草稿并提示 `AI_NOT_CONFIGURED`。

安全：只允许 http/https；超时固定；不把上游异常原文透给用户（避免泄露密钥/地址）。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx
from app.core.time import biz_today

PROMPT = """你是食品包装信息提取器。只输出一个 JSON 对象，不要解释：
{
  "name": "商品名称（去掉营销词）",
  "brand": "品牌或空串",
  "specification": "规格，如 500g",
  "barcode": "条形码数字或空串",
  "nutrition": [{"code": "calories|protein|fat|carbs|fiber|sodium",
                 "value": "数字", "basis_amount": "100", "basis_unit": "g"}],
  "production_date": "YYYY-MM-DD 或 null",
  "expiry_date": "YYYY-MM-DD 或 null",
  "shelf_life_days": 天数或 null
}
注意：包装上常同时印「生产日期」与「保质期/此日期前食用」，不要把生产日期填进 expiry_date；
无法确定的字段用 null，不要猜。"""


class AIProviderError(RuntimeError):
    """上游识别失败（网络/格式/鉴权），上层据此降级为空白草稿。"""


@dataclass
class Recognition:
    draft: dict = field(default_factory=dict)
    provider: str = "manual"
    model: str = ""
    warnings: list[dict] = field(default_factory=list)


def _stub(hint: str) -> dict:
    """离线样例：营养值与 PRD 验收用例一致，便于人工比对。"""
    today = biz_today()
    return {
        "name": hint or "识别样例食材",
        "brand": "",
        "specification": "500g",
        "barcode": "",
        "nutrition": [
            {"code": "calories", "value": "165", "basis_amount": "100", "basis_unit": "g"},
            {"code": "protein", "value": "31", "basis_amount": "100", "basis_unit": "g"},
            {"code": "fat", "value": "3.6", "basis_amount": "100", "basis_unit": "g"},
        ],
        "production_date": (today - timedelta(days=10)).isoformat(),
        "expiry_date": (today + timedelta(days=20)).isoformat(),
        "shelf_life_days": None,
    }


def recognize(
    *,
    cfg: dict,
    image_bytes: bytes | None,
    mime: str,
    hint: str,
) -> Recognition:
    kind = (cfg.get("kind") or "none").strip()
    if not cfg.get("enabled") or kind == "none":
        return Recognition(draft={}, provider="manual", model="")

    if kind == "stub":
        return Recognition(draft=_stub(hint), provider="stub", model="stub-v1")

    if kind != "openai_compatible":
        raise AIProviderError(f"不支持的识别 provider：{kind}")
    if not image_bytes:
        raise AIProviderError("缺少图片")

    base = (cfg.get("base_url") or "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise AIProviderError("provider.base_url 必须是 http(s) 地址")
    model = cfg.get("model") or ""
    if not model:
        raise AIProviderError("provider.model 未配置")

    data_url = f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT + (f"\n提示：{hint}" if hint else "")},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    try:
        with httpx.Client(timeout=int(cfg.get("timeout_seconds") or 30)) as client:
            resp = client.post(f"{base}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        content = body["choices"][0]["message"]["content"]
        draft = json.loads(content) if isinstance(content, str) else content
        if not isinstance(draft, dict):
            raise ValueError("返回不是 JSON 对象")
        return Recognition(draft=draft, provider="openai_compatible", model=model)
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        # 不把上游原文透出，避免泄露 URL / key
        raise AIProviderError(f"视觉模型调用失败：{type(exc).__name__}") from exc


def today() -> date:
    return biz_today()
