"""系统级接口：健康检查、连通性探测、数据库自检、前端日志上报。

这些接口不需要认证，用于容器健康检查与前端启动时的连通性判断。
**响应统一使用 {success, data, message, request_id} 信封**（docs/api.md §1.2），
前端 axios 拦截器按 data 取值，不要返回裸对象。
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import db_info, engine
from app.db.session import ping as db_ping

log = get_logger(__name__)
router = APIRouter(tags=["system"])


def envelope(request: Request, data: dict, message: str = "") -> dict:
    return {
        "success": True,
        "data": data,
        "message": message,
        "request_id": getattr(request.state, "request_id", ""),
    }


@router.get("/health", summary="健康检查（供容器探针）")
def health(request: Request, response: Response) -> dict:
    ok = db_ping()
    # 数据库不可用时返回 503，让编排器能正确判定；body 仍给明细，便于区分"库没起"还是"应用挂了"
    if not ok:
        response.status_code = 503
    return envelope(
        request,
        {"status": "ok" if ok else "degraded", "db": ok, "version": __version__, "env": settings.env},
    )


@router.get("/ping", summary="客户端探测：确认服务身份与握手状态")
def ping(request: Request) -> dict:
    initialized: bool | None = None
    if db_ping():
        try:
            with engine.connect() as conn:
                initialized = bool(conn.execute(text("SELECT 1 FROM devices LIMIT 1")).first())
        except Exception:
            initialized = False
    now = datetime.now(UTC)
    return envelope(
        request,
        {
            "name": "freshkeep",
            "version": __version__,
            "api": 1,
            "initialized": initialized,
            "needs_pair": False if initialized is None else (not initialized),
            "server_time": now.astimezone(ZoneInfo(settings.tz_biz)).isoformat(),
        },
    )


@router.get("/system/db", summary="数据库连通性与结构自检")
def system_db(request: Request, response: Response) -> dict:
    info = db_info()
    if not info.get("connected"):
        response.status_code = 503
    return envelope(request, info)


class ClientLogEntry(BaseModel):
    scope: str = Field(default="unknown", max_length=64)
    message: str = Field(default="", max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    stack: str | None = Field(default=None, max_length=8000)
    ts: str | None = None


class ClientLogBatch(BaseModel):
    entries: list[ClientLogEntry] = Field(default_factory=list, max_length=20)


@router.post("/system/client-logs", status_code=202, summary="接收前端上报的错误日志")
def client_logs(request: Request, payload: ClientLogBatch) -> dict:
    """把前端错误写进后端同一份日志，便于按时间/请求对齐排查。

    只记 warning，不影响请求成败；条数与字段长度都有上限，避免被打爆日志。
    """
    rid = getattr(request.state, "request_id", "")
    for entry in payload.entries:
        log.warning(
            "前端错误 scope=%s url=%s msg=%s",
            entry.scope,
            entry.url,
            entry.message,
            extra={"request_id": rid},
        )
    return envelope(request, {"received": len(payload.entries)}, "已记录")
