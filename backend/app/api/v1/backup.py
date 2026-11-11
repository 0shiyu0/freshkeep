"""备份、导出与定时任务（M7）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.services import backup as svc
from app.services.export import stream_csv

router = APIRouter(tags=["backup"])


@router.post("/backup", status_code=201, summary="立即生成逻辑备份")
def create(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.create_backup(db)
    return ok(request, data, f"已生成备份 {data['name']}")


@router.get("/backups", summary="备份列表")
def list_backups(
    request: Request,
    auth: AuthContext = Depends(get_current),
):
    items = svc.list_backups()
    return ok(request, {"items": items, "total": len(items)})


@router.post("/backups/{name}/verify", summary="校验备份可读性")
def verify(
    request: Request,
    name: str,
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.verify(name))


@router.get("/backups/{name}/download", summary="下载备份")
def download(
    name: str,
    auth: AuthContext = Depends(get_current),
):
    path = svc.resolve(name)
    return FileResponse(path, filename=path.name, media_type="application/gzip")


@router.get("/export/{kind}.csv", summary="导出 CSV（transactions / consumptions）")
def export_csv(
    kind: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    if kind not in ("transactions", "consumptions"):
        from app.core.errors import not_found

        raise not_found("不支持的导出类型")
    return StreamingResponse(
        stream_csv(db, kind),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )


@router.get("/tasks", summary="定时任务状态")
def tasks_status(
    request: Request,
    auth: AuthContext = Depends(get_current),
):
    from app.tasks.scheduler import status

    return ok(request, status())


@router.post("/tasks/{job_id}/run", summary="手动触发一次定时任务")
def run_task(
    request: Request,
    job_id: str,
    auth: AuthContext = Depends(get_current),
):
    from app.core.errors import validation_error
    from app.tasks.scheduler import run_now

    try:
        data = run_now(job_id)
    except ValueError as exc:
        raise validation_error(str(exc)) from exc
    return ok(request, data, f"已执行 {job_id}")
