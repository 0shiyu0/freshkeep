"""数据库连接与会话。

约定（见 AGENTS.md §4.2）：
- 一个业务操作一个事务，由 service 层用 `with session.begin()` 控制；
- 不在 API 层提交事务；
- 金额/重量字段在模型里用 Numeric，不用 Float。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"connect_timeout": 3},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 session，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """脚本/任务用：自动提交或回滚。"""
    db = SessionLocal()
    try:
        with db.begin():
            yield db
    finally:
        db.close()


def ping() -> bool:
    """健康检查用：能否连上库。3 秒超时由 connect_timeout 保证。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - 健康检查不区分错误类型
        return False
