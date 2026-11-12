"""日志与异常记录。

统一约定（见 AGENTS.md §12.3 的"已执行测试及结果"要求）：每条日志都带 `request_id`，
HTTP 访问日志与业务异常写同一套 handler，既输出到容器 stdout，也落文件 `$LOG_DIR/api.log`。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

_CONFIGURED = False

# 第三方库降噪：SQLAlchemy 的 echo 由 DB_ECHO 单独控制
_NOISY = ("uvicorn.access", "sqlalchemy.engine.Engine", "apscheduler")


class JsonFormatter(logging.Formatter):
    """一行一个 JSON，便于 grep / 后续接采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "client", "code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    """本地开发更好读的格式。"""

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", "-")
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<5} [{rid}] {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> None:
    """幂等初始化：控制台 + 滚动文件。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level, logging.INFO)
    formatter: logging.Formatter = JsonFormatter() if settings.log_json else PlainFormatter()

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            Path(settings.log_dir) / "api.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # 目录不可写时只保留控制台输出，不能因此启动失败
        logging.getLogger(__name__).warning("日志文件不可用，仅输出到控制台：%s", exc)

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    if settings.db_echo:
        logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.INFO)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, exc: Exception, *, request_id: str = "", extra: dict | None = None) -> None:
    """统一记录未预期异常，保留堆栈。"""
    ctx = {"request_id": request_id} if request_id else {}
    if extra:
        ctx.update(extra)
    logger.error("未处理异常：%s: %s", type(exc).__name__, exc, exc_info=True, extra=ctx)
