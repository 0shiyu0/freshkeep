"""配置：只从环境变量读取，不引入 pydantic-settings（少一个依赖）。"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_list(key: str, default: str = "") -> list[str]:
    raw = _env(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    """运行时配置。所有字段都能被同名环境变量覆盖。"""

    # 服务
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8080") or 8080))
    workers: int = field(default_factory=lambda: int(_env("WORKERS", "2") or 2))

    # 数据
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+psycopg://freshkeep:freshkeep@localhost:5432/freshkeep",
        )
    )
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))
    static_dir: Path = field(
        default_factory=lambda: Path(
            _env("STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
        )
    )

    # 安全：只允许内网与组网网段
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
    trust_proxy: bool = field(default_factory=lambda: _env("TRUST_PROXY", "0") == "1")

    # 业务
    tz_biz: str = field(default_factory=lambda: _env("TZ_BIZ", "Asia/Shanghai"))
    token_ttl_days: int = field(default_factory=lambda: int(_env("TOKEN_TTL_DAYS", "0") or 0))
    pair_code_ttl_minutes: int = field(
        default_factory=lambda: int(_env("PAIR_CODE_TTL_MINUTES", "10") or 10)
    )

    def allow_networks(self) -> list[ipaddress._BaseNetwork]:
        """解析 ALLOW_CIDR；非法项直接跳过并保持可用（失败即拒绝的策略在中间件里）。"""
        nets = []
        for cidr in self.allow_cidr:
            try:
                nets.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                continue
        return nets


settings = Settings()
