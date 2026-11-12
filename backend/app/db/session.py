"""数据库连接与会话。

约定（AGENTS.md §4.2）：一个业务操作一个事务，由 service 层用 `with session.begin()` 控制；
不在 API 层提交事务；金额/重量字段用 Numeric，不用 Float。

连接池参数全部来自环境变量，见 app/core/config.py：
  DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_POOL_RECYCLE
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import settings
from app.core.logging import get_logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

log = get_logger(__name__)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,          # 取连接前先探活，避免拿到被数据库单方面关闭的连接
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,   # 小于 PG 的 idle_session_timeout
    connect_args={"connect_timeout": 5, "application_name": settings.app_name},
    echo=settings.db_echo,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 session，请求结束自动关闭（未提交的改动随之回滚）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """脚本/任务用：自动提交，异常自动回滚。"""
    db = SessionLocal()
    try:
        with db.begin():
            yield db
    finally:
        db.close()


def ping() -> bool:
    """能否连上库。健康检查用，不抛异常。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("数据库探活失败：%s", exc)
        return False


def db_info() -> dict:
    """返回数据库版本、业务表数、迁移版本与连接池状态，用于 /api/v1/system/db 与联调自查。"""
    info: dict = {"connected": False}
    try:
        with engine.connect() as conn:
            info["server_version"] = conn.execute(text("SHOW server_version")).scalar_one()
            info["database"] = conn.execute(text("SELECT current_database()")).scalar_one()
            info["tables"] = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE' "
                    "AND table_name <> 'alembic_version'"
                )
            ).scalar_one()
            try:
                info["migration"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            except Exception:
                info["migration"] = None
            info["pool"] = {
                # size = 常驻连接数；max_overflow = 允许的临时超出上限；checked_out = 当前借出数
                # 注：pool.overflow() 在连接归还后会变负，语义容易误读，这里只报配置上限
                "size": engine.pool.size(),
                "max_overflow": settings.db_max_overflow,
                "checked_out": engine.pool.checkedout(),
            }
            info["connected"] = True
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info
