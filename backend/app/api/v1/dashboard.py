"""首页统计（M6）：库存价值、期间金额、最近入库、临期提醒、营养汇总。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.schemas.dashboard import DashboardNutrition, DashboardSummary
from app.services.dashboard import nutrition as build_nutrition
from app.services.dashboard import summary as build_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", summary="首页汇总")
def summary(
    request: Request,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """库存价值 + 期间采购/消耗/报损金额 + 消耗比例 + 最近入库 + 临期计数。

    `consumption_ratio` 在期间无采购时为 null（不是 0），避免把无数据读成 0%。
    """
    data = build_summary(db, from_date=from_date, to_date=to_date)
    return ok(request, DashboardSummary.model_validate(data).model_dump(mode="json"))


@router.get("/nutrition", summary="营养摄入汇总（按消耗快照估算）")
def nutrition(
    request: Request,
    period: str = Query(default="today", pattern="^(today|3d|week|month)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """`has_records=false` 表示窗口内没有任何已完成消耗，与「摄入为 0」不是一回事。"""
    data = build_nutrition(db, period=period)
    return ok(request, DashboardNutrition.model_validate(data).model_dump(mode="json"))
