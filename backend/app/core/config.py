"""配置：只从环境变量读取，不引入 pydantic-settings（少一个依赖）。"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path


def _repo_root() -> Path:
    """仓库根目录（app/core/config.py → backend/app/core → 上三级）。"""
    return Path(__file__).resolve().parents[3]


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key, "").lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(key: str, default: str = "") -> list[str]:
    raw = _env(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    """运行时配置。所有字段都能被同名环境变量覆盖。"""

    # ---- 应用 ----
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "freshkeep"))
    env: str = field(default_factory=lambda: _env("APP_ENV", "dev"))
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    workers: int = field(default_factory=lambda: _env_int("WORKERS", 2))

    # ---- 日志 ----
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())
    # 容器里由 docker-compose 指定 /data/logs；本地开发回落到仓库根的 storage/logs
    log_dir: Path = field(
        default_factory=lambda: Path(
            _env("LOG_DIR", str(_repo_root() / "storage" / "logs"))
        )
    )
    log_json: bool = field(default_factory=lambda: _env_bool("LOG_JSON", True))
    access_log: bool = field(default_factory=lambda: _env_bool("ACCESS_LOG", True))

    # ---- 数据库 ----
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+psycopg://freshkeep:freshkeep@localhost:5432/freshkeep",
        )
    )
    db_pool_size: int = field(default_factory=lambda: _env_int("DB_POOL_SIZE", 5))
    db_max_overflow: int = field(default_factory=lambda: _env_int("DB_MAX_OVERFLOW", 10))
    db_pool_timeout: int = field(default_factory=lambda: _env_int("DB_POOL_TIMEOUT", 10))
    db_pool_recycle: int = field(default_factory=lambda: _env_int("DB_POOL_RECYCLE", 1800))
    db_echo: bool = field(default_factory=lambda: _env_bool("DB_ECHO", False))

    # ---- 存储 ----
    # 容器里由 docker-compose 指定 /data/*；本地开发/测试回落到仓库内的 storage/ 与 backups/，
    # 这样不需要 /data 目录也能启动（曾因硬编码 /data 导致上传接口 500）。
    data_dir: Path = field(
        default_factory=lambda: Path(_env("DATA_DIR", str(_repo_root())))
    )
    storage_dir: Path = field(
        default_factory=lambda: Path(_env("STORAGE_DIR", str(_repo_root() / "storage")))
    )
    backup_dir: Path = field(
        default_factory=lambda: Path(_env("BACKUP_DIR", str(_repo_root() / "backups")))
    )
    # 生产由 nginx 托管前端；本地开发可置 1 让 FastAPI 直接托管 dist
    serve_static: bool = field(default_factory=lambda: _env_bool("SERVE_STATIC", False))
    # 定时任务（M7）：容器里设为 true；测试与本地默认关闭
    enable_scheduler: bool = field(default_factory=lambda: _env_bool("ENABLE_SCHEDULER", False))
    static_dir: Path = field(
        default_factory=lambda: Path(
            _env("STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
        )
    )

    # ---- 安全 ----
    allow_cidr: list[str] = field(
        default_factory=lambda: _env_list(
            "ALLOW_CIDR",
            "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10,127.0.0.1/32",
        )
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "CORS_ORIGINS", "capacitor://localhost,http://localhost,http://localhost:5173"
        )
    )
    trust_proxy: bool = field(default_factory=lambda: _env_bool("TRUST_PROXY", False))

    # ---- 业务 ----
    tz_biz: str = field(default_factory=lambda: _env("TZ_BIZ", "Asia/Shanghai"))
    token_ttl_days: int = field(default_factory=lambda: _env_int("TOKEN_TTL_DAYS", 0))
    pair_code_ttl_minutes: int = field(default_factory=lambda: _env_int("PAIR_CODE_TTL_MINUTES", 10))

    def allow_networks(self) -> list[ipaddress._BaseNetwork]:
        """解析 ALLOW_CIDR；非法项跳过（中间件对不在名单内的请求一律拒绝）。"""
        nets = []
        for cidr in self.allow_cidr:
            try:
                nets.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                continue
        return nets


settings = Settings()
