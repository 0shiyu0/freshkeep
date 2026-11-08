"""文件上传与读取（食材图片）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import conflict, not_found
from app.db.session import get_db
from app.models import FileAsset, Ingredient
from app.schemas.common import ok
from app.services import files as file_svc

router = APIRouter(prefix="/files", tags=["files"])


def _to_out(asset: FileAsset) -> dict:
    return {
        "id": str(asset.id),
        "url": f"/api/v1/files/{asset.id}/raw",
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "checksum": asset.checksum,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


@router.post("/upload", status_code=201, summary="上传图片（jpg/png/webp，≤5MB）")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    data = await file.read()
    asset = file_svc.save_image(db, data, file.content_type)
    db.commit()
    return ok(request, _to_out(asset), "上传成功")


@router.get("/{file_id}", summary="文件元信息")
def detail(
    request: Request,
    file_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    asset = db.get(FileAsset, file_id)
    if asset is None:
        raise not_found("文件不存在")
    return ok(request, _to_out(asset))


@router.get("/{file_id}/raw", summary="读取图片原始字节（需要登录态 Cookie）")
def raw(
    file_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Web 端 <img> 自动带 HttpOnly Cookie，可直接引用该地址。

    原生 App 的 <img> 带不上 Bearer，需用 axios 取回 blob 再赋给 src（见前端 api/files.ts）。
    """
    asset = db.get(FileAsset, file_id)
    if asset is None:
        raise not_found("文件不存在")
    path = file_svc.absolute_path(asset)
    if not path.exists():
        raise not_found("文件已丢失")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/{file_id}", summary="删除图片（被食材引用时拒绝）")
def delete(
    request: Request,
    file_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    asset = db.get(FileAsset, file_id)
    if asset is None:
        raise not_found("文件不存在")
    used = db.execute(
        select(func.count()).select_from(Ingredient).where(Ingredient.image_asset_id == file_id)
    ).scalar_one()
    if used:
        raise conflict(f"该图片被 {used} 个食材引用，请先解除引用")
    file_svc.delete_asset(db, asset)
    db.commit()
    return ok(request, {"deleted": True}, "图片已删除")
