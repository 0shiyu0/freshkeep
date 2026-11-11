"""采购建议（8.10）：只读计算。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.services.purchase import suggestions

router = APIRouter(prefix="/purchase", tags=["purchase"])


@router.get("/suggestions", summary="低库存采购建议")
def purchase_suggestions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, suggestions(db, limit=limit))
