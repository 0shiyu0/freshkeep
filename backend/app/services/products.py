"""商品信息查询（8.2 条码 / 8.3 可配置外部数据源）。

顺序：本地条码库 → 外部数据源（若已配置）→ 都没有则返回 `found=false`。
外部源失败不影响本地命中，也不抛 500（返回 `source_error` 供前端提示）。
安全：只允许 http/https，且拒绝内网/回环地址（防 SSRF）。
"""
from __future__ import annotations

import ipaddress
import socket
from decimal import Decimal
from urllib.parse import urlparse

import httpx
from app.models import Ingredient, IngredientBarcode
from app.services.ai.config import read_product_source
from app.services.ai.validate import normalize_barcode
from sqlalchemy import select
from sqlalchemy.orm import Session

PRIVATE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("数据源地址必须是 http(s)")
    host = parsed.hostname.lower()
    if host in PRIVATE_HOSTS:
        raise ValueError("数据源地址不能是内网地址")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError("数据源域名无法解析") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError("数据源地址解析到内网，已拒绝")


def _norm_from_off(product: dict, barcode: str) -> dict:
    nutriments = product.get("nutriments") or {}
    nutrition = []
    mapping = {
        "calories": ("energy-kcal_100g", "kcal"),
        "protein": ("proteins_100g", "g"),
        "fat": ("fat_100g", "g"),
        "carbs": ("carbohydrates_100g", "g"),
        "fiber": ("fiber_100g", "g"),
        "sodium": ("sodium_100g", "g"),
    }
    for code, (key, unit) in mapping.items():
        value = nutriments.get(key)
        if value is None:
            continue
        dec = Decimal(str(value))
        if code == "sodium" and unit == "g":
            dec = dec * 1000  # 包装上通常标 mg
            unit = "mg"
        nutrition.append({
            "code": code, "value": str(dec.quantize(Decimal("0.0001"))),
            "basis_amount": "100", "basis_unit": "g", "unit_hint": unit,
        })
    return {
        "name": (product.get("product_name") or product.get("generic_name") or "").strip(),
        "brand": (product.get("brands") or "").split(",")[0].strip(),
        "specification": (product.get("quantity") or "").strip(),
        "barcode": barcode,
        "nutrition": nutrition,
        "source_label": "OpenFoodFacts",
    }


def lookup(db: Session, raw_barcode: str) -> dict:
    barcode = normalize_barcode(raw_barcode)
    if not barcode:
        return {"found": False, "source": "none", "barcode": "", "message": "条码为空"}

    # 1) 本地条码库
    local = db.execute(
        select(IngredientBarcode, Ingredient)
        .join(Ingredient, Ingredient.id == IngredientBarcode.ingredient_id)
        .where(IngredientBarcode.barcode == barcode)
    ).first()
    if local is not None:
        _, ing = local
        return {
            "found": True,
            "source": "local",
            "barcode": barcode,
            "ingredient_id": ing.id,
            "ingredient_name": ing.name,
            "brand": ing.brand,
            "specification": ing.specification,
            "product": None,
        }

    # 2) 外部数据源
    cfg = read_product_source(db)
    kind = (cfg.get("kind") or "none").strip()
    if not cfg.get("enabled") or kind == "none":
        return {
            "found": False,
            "source": "none",
            "barcode": barcode,
            "message": "本地无此条码，未配置外部数据源",
        }

    try:
        with httpx.Client(timeout=int(cfg.get("timeout_seconds") or 8), follow_redirects=False) as client:
            if kind == "openfoodfacts":
                base = (cfg.get("base_url") or "https://world.openfoodfacts.org").rstrip("/")
                url = f"{base}/api/v2/product/{barcode}.json"
            elif kind == "custom":
                base = (cfg.get("base_url") or "").rstrip("/")
                if not base:
                    raise ValueError("custom 数据源未配置 base_url")
                url = base.replace("{barcode}", barcode)
                if "{barcode}" not in base:
                    url = f"{base}?barcode={barcode}"
            else:
                raise ValueError(f"不支持的数据源类型：{kind}")

            _assert_public_url(url)
            resp = client.get(url, headers={"User-Agent": "FreshKeep/1.0"})
            if resp.status_code == 404:
                return {"found": False, "source": kind, "barcode": barcode, "message": "外部数据源未收录"}
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {
            "found": False,
            "source": kind,
            "barcode": barcode,
            "source_error": str(exc)[:200],
            "message": "外部数据源查询失败，可手动录入",
        }

    if kind == "openfoodfacts":
        if body.get("status") != 1:
            return {"found": False, "source": kind, "barcode": barcode, "message": "外部数据源未收录"}
        product = _norm_from_off(body.get("product") or {}, barcode)
    else:
        product = body if isinstance(body, dict) else {}

    if not product.get("name"):
        return {"found": False, "source": kind, "barcode": barcode, "message": "外部数据源缺少商品名称"}

    return {"found": True, "source": kind, "barcode": barcode, "product": product}
