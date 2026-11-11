"""商品信息查询（8.2 条码 / 8.3 外部数据源配置）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.ai import ProductSourceIn
from app.schemas.common import ok
from app.services.ai.config import PRODUCT_KEY, mask, read_product_source, write_setting
from app.services.products import lookup

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/lookup", summary="按条码查询商品（本地优先，其次外部源）")
def product_lookup(
    request: Request,
    barcode: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, lookup(db, barcode))


@router.get("/source", summary="外部数据源配置（密钥脱敏）")
def get_source(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    cfg = read_product_source(db)
    return ok(request, {**cfg, "api_key": mask(cfg.get("api_key") or "")})


@router.put("/source", summary="保存外部数据源配置")
def put_source(
    request: Request,
    payload: ProductSourceIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    value = payload.model_dump()
    if "*" in (value.get("api_key") or ""):
        value["api_key"] = read_product_source(db).get("api_key") or ""
    write_setting(db, PRODUCT_KEY, value)
    db.commit()
    return ok(request, {"saved": True}, "数据源已保存")
