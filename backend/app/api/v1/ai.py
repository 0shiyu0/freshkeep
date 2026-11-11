"""AI 辅助接口（阶段 8）：识别只产生草稿，确认才建档/入库。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.ai import (
    ProviderSettingsIn,
    RecognitionConfirmIn,
    RecognitionIn,
    RecognitionPatch,
)
from app.schemas.common import ok
from app.services.ai import confirm as confirm_draft
from app.services.ai import create_draft, reject, serialize, update_draft
from app.services.ai.config import mask, read_ai, write_setting

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/recognitions", status_code=201, summary="识别包装并生成待确认草稿")
def create_recognition(
    request: Request,
    payload: RecognitionIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """只写 recognition_drafts，**不产生任何库存变动**。"""
    data = create_draft(
        db,
        image_file_id=payload.image_file_id,
        hint=payload.hint,
        manual=payload.manual,
        device_id=auth.device.id,
    )
    db.commit()
    return ok(request, data, "已生成待确认信息")


@router.get("/recognitions/{draft_id}", summary="查看待确认草稿")
def get_recognition(
    request: Request,
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    from app.core.errors import not_found
    from app.models import RecognitionDraft

    row = db.get(RecognitionDraft, draft_id)
    if row is None:
        raise not_found("识别草稿不存在")
    return ok(request, serialize(row))


@router.patch("/recognitions/{draft_id}", summary="人工修正草稿字段")
def patch_recognition(
    request: Request,
    draft_id: uuid.UUID,
    payload: RecognitionPatch,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = update_draft(db, draft_id, payload.patch)
    db.commit()
    return ok(request, data, "已保存修正")


@router.post("/recognitions/{draft_id}/confirm", summary="确认并建档或入库")
def confirm_recognition(
    request: Request,
    draft_id: uuid.UUID,
    payload: RecognitionConfirmIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """确认后才写入业务数据；入库仍走路由既有五步事务。"""
    data = confirm_draft(
        db,
        draft_id,
        target=payload.target,
        ingredient_id=payload.ingredient_id,
        patch=payload.patch,
        device_id=auth.device.id,
    )
    db.commit()
    return ok(request, data, "已确认")


@router.post("/recognitions/{draft_id}/reject", summary="拒绝识别结果")
def reject_recognition(
    request: Request,
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = reject(db, draft_id)
    db.commit()
    return ok(request, data, "已忽略")


@router.get("/settings", summary="识别配置（密钥脱敏）")
def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    cfg = read_ai(db)
    return ok(request, {**cfg, "api_key": mask(cfg.get("api_key") or "")})


@router.put("/settings", summary="保存识别配置")
def put_settings(
    request: Request,
    payload: ProviderSettingsIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    from app.services.ai.config import AI_KEY

    value = payload.model_dump()
    # 前端回显的是脱敏 key（含 *），原样回传时保留旧值
    if "*" in (value.get("api_key") or ""):
        value["api_key"] = read_ai(db).get("api_key") or ""
    write_setting(db, AI_KEY, value)
    db.commit()
    return ok(request, {"saved": True}, "配置已保存")
