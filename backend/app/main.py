"""FastAPI 装配。

职责边界（AGENTS.md §2）：本文件只做中间件、异常处理、路由挂载、静态托管；
业务逻辑在 app/api/v1 → app/services。
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import ApiError
from app.core.logging import get_logger, log_exception, setup_logging
from app.core.middleware import CidrMiddleware, IdempotencyMiddleware

setup_logging()
log = get_logger("app.main")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动定时任务（ENABLE_SCHEDULER=true 时）；关闭时优雅停止。"""
    from app.tasks.scheduler import shutdown_scheduler, start_scheduler

    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(
    title="鲜度 FreshKeep API",
    version=__version__,
    description="家庭食材库存与营养管理 · 自托管 API",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# 注册顺序＝执行顺序的反序（后加的先执行），因此最外层安全闸门最后加：
#   CidrMiddleware（网段） → IdempotencyMiddleware（幂等） → 请求上下文 → CORS → 路由
app.add_middleware(CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,          # App 走 Bearer，不需要带 Cookie
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["X-Request-Id", "Idempotency-Replayed"],
)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(CidrMiddleware)


# ---------------------------------------------------------------- 中间件


@app.middleware("http")
async def request_context(request: Request, call_next):
    """生成 request_id、记录访问日志、兜底未处理异常。

    访问日志字段 method/path/status/duration_ms/client/request_id 与异常日志同一套 formatter，
    可按 request_id 把一次请求的所有日志串起来。
    """
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        cost = (time.perf_counter() - started) * 1000
        log_exception(
            log,
            exc,
            request_id=request_id,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": round(cost, 2),
                "client": request.client.host if request.client else None,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": "服务内部错误，请查看服务端日志"},
                "request_id": request_id,
            },
            headers={"X-Request-Id": request_id},
        )

    cost = (time.perf_counter() - started) * 1000
    response.headers["X-Request-Id"] = request_id
    if settings.access_log:
        log.info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            cost,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(cost, 2),
                "client": request.client.host if request.client else None,
            },
        )
    return response


# ---------------------------------------------------------------- 异常处理


def _fail(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body: dict = {
        "success": False,
        "error": {"code": code, "message": message},
        "request_id": getattr(request.state, "request_id", ""),
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    # 业务异常属预期内的失败，info 级别记录，不写堆栈
    log.info(
        "业务异常 %s: %s",
        exc.code,
        exc.message,
        extra={
            "request_id": getattr(request.state, "request_id", ""),
            "code": exc.code,
            "path": request.url.path,
            "status": exc.status_code,
        },
    )
    return _fail(request, exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    log.info(
        "参数校验失败 %s: %s",
        request.url.path,
        fields[:3],
        extra={"request_id": getattr(request.state, "request_id", ""), "status": 400},
    )
    return _fail(request, 400, "VALIDATION_ERROR", "参数不合法", {"fields": fields})


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    mapping = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    return _fail(request, exc.status_code, mapping.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))


# ---------------------------------------------------------------- 路由


@app.get("/health", include_in_schema=False)
def root_health() -> dict:
    """容器探针走最短路径（也可用 /api/v1/health）。"""
    from app.db.session import ping as db_ping

    ok = db_ping()
    return {"status": "ok" if ok else "degraded", "db": ok, "version": __version__}


app.include_router(api_router, prefix=API_PREFIX)

# 本地开发用：SERVE_STATIC=1 时由 FastAPI 托管前端产物（生产由 nginx 托管）
if settings.serve_static and settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="web")
    log.info("已启用内置静态托管：%s", settings.static_dir)
