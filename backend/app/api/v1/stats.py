"""统计接口（阶段 6）：一次返回首页需要的全部统计维度。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.schemas.stats import StatsOverview
from app.services.stats import overview as build_overview

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", summary="首页统计（库存价值/趋势/分类/排行/周转）")
def overview(
    request: Request,
    granularity: str = Query(default="day", pattern="^(day|week|month|year)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """金额全部来自流水聚合；库存价值取剩余成本，与采购总额是两回事。"""
    data = build_overview(db, granularity=granularity, from_date=from_date, to_date=to_date)
    return ok(request, StatsOverview.model_validate(data).model_dump(mode="json"))
