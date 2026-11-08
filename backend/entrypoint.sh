#!/bin/sh
# 容器入口：等库就绪 → 执行迁移 → 起服务
set -e

echo "[entrypoint] 等待数据库…"
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.core.config import settings

for i in range(30):
    try:
        with create_engine(settings.database_url, connect_args={"connect_timeout": 3}).connect() as c:
            c.execute(text("SELECT 1"))
        print("[entrypoint] 数据库已就绪")
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"[entrypoint] 第 {i + 1} 次等待：{type(e).__name__}")
        time.sleep(2)
print("[entrypoint] 数据库连接失败，退出")
sys.exit(1)
PY

echo "[entrypoint] 执行数据库迁移…"
alembic upgrade head

echo "[entrypoint] 启动服务 :8080"
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers "${WORKERS:-2}" --proxy-headers
