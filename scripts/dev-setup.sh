#!/bin/sh
# 一键准备开发环境（幂等，可重复执行）
#   ./scripts/dev-setup.sh
# 环境变量：
#   PIP_INDEX_URL   pip 镜像源，默认清华
#   SKIP_FRONTEND=1 跳过前端依赖与构建
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MIRROR=${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}

say() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# ---------------------------------------------------------------- 后端
say "后端依赖（${ROOT}/backend）"
cd "${ROOT}/backend"

if command -v uv >/dev/null 2>&1; then
  echo "检测到 uv，用它安装（通常 1~2 秒）"
  [ -d .venv ] || uv venv .venv
  uv pip install --python .venv/bin/python -i "$MIRROR" -r requirements.txt
else
  echo "未检测到 uv，回退到 pip（镜像 + 仅二进制轮子，约 25 秒）"
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install --only-binary=:all: -i "$MIRROR" -r requirements.txt
fi

echo "后端依赖自检："
.venv/bin/python -c "import fastapi, sqlalchemy, psycopg, alembic, pypinyin; print('  ok')"

# ---------------------------------------------------------------- 前端
if [ "${SKIP_FRONTEND:-0}" = "1" ]; then
  echo "跳过前端（SKIP_FRONTEND=1）"
else
  say "前端依赖（${ROOT}/frontend）"
  cd "${ROOT}/frontend"
  if [ ! -d node_modules ]; then
    npm ci --no-audit --no-fund
  else
    echo "node_modules 已存在，跳过安装"
  fi
  say "构建前端产物 dist/"
  npm run build
fi

# ---------------------------------------------------------------- 数据库
say "数据库"
if command -v psql >/dev/null 2>&1; then
  if psql -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw freshkeep; then
    echo "库 freshkeep 已存在；如需重建：dropdb freshkeep && createdb freshkeep"
  else
    createdb freshkeep && echo "已创建库 freshkeep"
  fi
  echo "应用 DDL…"
  psql -d freshkeep -q -f "${ROOT}/database/001_init.sql"
  echo "跑数据库自检（期望最后一行 NOTICE 为全部通过）…"
  psql -d freshkeep -f "${ROOT}/database/002_acceptance_check.sql" 2>&1 | grep -E "NOTICE|ERROR" | sed 's/^NOTICE:  /  /'
else
  echo "未找到 psql，跳过建库。安装方式见 docs/ENV_SETUP.md §2"
fi

say "完成"
echo "跑测试：cd backend && .venv/bin/python -m pytest"
echo "起服务：cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8080"
