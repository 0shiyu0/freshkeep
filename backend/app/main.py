"""FastAPI 应用装配。

职责边界（AGENTS.md §2）：
- 本文件只做：中间件、异常处理、路由挂载、静态托管；
- 业务逻辑一律在 app/api/v1 → app/services 里。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.errors import ApiError
from app.db.session import engine, ping as db_ping

API_PREFIX = "/api/v1"

app = FastAPI(
    title="鲜度 FreshKeep API",
    version=__version__,
    description="家庭食材库存与营养管理 · 自托管 API",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,          # App 走 Bearer，不需要带 Cookie
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["X-Request-Id"],
)


# ---------------------------------------------------------------- 中间件


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求生成 request_id，写进响应头与日志，便于按 id 反查。"""
    request.state.request_id = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


# ---------------------------------------------------------------- 异常处理


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.to_dict(),
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 Pydantic 的字段错误压平成 details.fields，客户端不用解析嵌套结构。"""
    fields = [
        {"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": "参数不合法", "details": {"fields": fields}},
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


# ---------------------------------------------------------------- 基础接口


@app.get("/health", tags=["system"])
def health() -> dict:
    """容器健康检查。db 为 false 时整机不可用，但仍返回 200 让编排器看到具体原因。"""
    db_ok = db_ping()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "version": __version__}


@app.get(f"{API_PREFIX}/ping", tags=["system"])
def ping() -> dict:
    """客户端探测：确认是鲜度的服务、是否需要配对、服务器时间。"""
    initialized: bool | None = None
    if db_ping():
        try:
            with engine.connect() as conn:
                initialized = bool(conn.execute(text("SELECT 1 FROM devices LIMIT 1")).first())
        except Exception:  # noqa: BLE001 - 表尚未建时视为未初始化
            initialized = False
    now = datetime.now(timezone.utc)
    return {
        "name": "freshkeep",
        "version": __version__,
        "api": 1,
        "initialized": initialized,
        "needs_pair": False if initialized is None else (not initialized),
        "server_time": now.astimezone(ZoneInfo(settings.tz_biz)).isoformat(),
    }


# ---------------------------------------------------------------- 静态托管
# 必须放在所有 API 路由之后：/ 的挂载会兜住其余路径
if settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="web")
