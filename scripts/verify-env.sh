#!/bin/sh
# 环境体检：逐项检查并给出「通过/缺失」与补救命令
#   ./scripts/verify-env.sh
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass() { printf '  \033[32m✓\033[0m %-22s %s\n' "$1" "$2"; }
warn() { printf '  \033[33m!\033[0m %-22s %s\n' "$1" "$2"; }
fail() { printf '  \033[31m✗\033[0m %-22s %s\n' "$1" "$2"; }

echo "环境体检（${ROOT}）"

# Python
if command -v python3 >/dev/null 2>&1; then
  pass "Python" "$(python3 -V 2>&1)"
else
  fail "Python" "未安装"
fi

# 后端 venv 与依赖
if [ -x "${ROOT}/backend/.venv/bin/python" ]; then
  if "${ROOT}/backend/.venv/bin/python" -c "import fastapi" 2>/dev/null; then
    pass "后端依赖" "$(${ROOT}/backend/.venv/bin/python -c 'import fastapi,sqlalchemy;print("fastapi",fastapi.__version__,"sqlalchemy",sqlalchemy.__version__)')"
  else
    fail "后端依赖" "venv 存在但依赖缺失 → ./scripts/dev-setup.sh"
  fi
else
  fail "后端 venv" "不存在 → ./scripts/dev-setup.sh"
fi

# Node / npm
if command -v node >/dev/null 2>&1; then pass "Node" "$(node -v)"; else fail "Node" "未安装"; fi
if [ -d "${ROOT}/frontend/node_modules" ]; then pass "前端依赖" "node_modules 已存在"; else warn "前端依赖" "未安装 → cd frontend && npm ci"; fi
if [ -d "${ROOT}/frontend/dist" ]; then pass "前端产物" "dist/ 已构建"; else warn "前端产物" "未构建 → cd frontend && npm run build"; fi

# PostgreSQL
if command -v psql >/dev/null 2>&1; then
  VER=$(psql --version 2>/dev/null)
  if psql -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw freshkeep; then
    N=$(psql -d freshkeep -tAc "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'" 2>/dev/null || echo 0)
    if [ "${N:-0}" -ge 25 ]; then pass "PostgreSQL" "$VER，freshkeep 库 $N 张表"
    else warn "PostgreSQL" "$VER，库存在但表数 $N（期望 25+）→ psql -d freshkeep -f database/001_init.sql"; fi
  else
    warn "PostgreSQL" "$VER，但库 freshkeep 不存在 → createdb freshkeep"
  fi
else
  warn "PostgreSQL" "未安装 → 见 docs/environment.md §2（或装 Docker 用容器版）"
fi

# Docker
if command -v docker >/dev/null 2>&1; then
  pass "Docker" "$(docker --version 2>/dev/null)"
else
  warn "Docker" "未安装（不影响本地开发，影响 compose 验证）"
fi

# Xcode
if xcodebuild -version >/dev/null 2>&1; then
  pass "Xcode" "$(xcodebuild -version 2>/dev/null | head -1)"
else
  warn "Xcode" "xcodebuild 不可用（可能只装了 CLT，只影响 iOS 出包）"
fi

# 测试
if [ -x "${ROOT}/backend/.venv/bin/python" ]; then
  cd "${ROOT}/backend" || exit 1
  OUT=$(.venv/bin/python -m pytest 2>&1 | grep -E "[0-9]+ passed" | tail -1)
  case "$OUT" in
    *failed*) fail "pytest" "$OUT" ;;
    *passed*) pass "pytest" "$OUT" ;;
    *) warn "pytest" "$OUT" ;;
  esac
fi

echo
echo "完整安装与验证步骤：docs/environment.md"
