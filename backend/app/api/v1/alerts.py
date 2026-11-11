"""临期提醒与通知中心（8.7 / 8.8）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.services import alerts as svc

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/scan", summary="立即扫描临期/过期/低库存并生成通知")
def scan(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.scan(db, days=days)
    db.commit()
    return ok(request, data, f"新增 {data['created']} 条提醒")


@router.get("/summary", summary="提醒汇总（首页铃铛）")
def summary(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.summary(db))


@router.get("/notifications", summary="通知中心列表")
def notifications(
    request: Request,
    status: str | None = Query(default="pending", pattern="^(pending|sent|skipped)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.list_notifications(db, status=status, page=page, page_size=page_size))


@router.post("/notifications/read-all", summary="全部标为已读")
def read_all(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    n = svc.mark_all_read(db)
    db.commit()
    return ok(request, {"updated": n})


@router.post("/notifications/{notification_id}/read", summary="标记单条已读")
def read_one(
    request: Request,
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    ok_flag = svc.mark_read(db, notification_id)
    db.commit()
    return ok(request, {"updated": 1 if ok_flag else 0})
