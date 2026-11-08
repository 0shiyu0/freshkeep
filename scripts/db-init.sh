#!/bin/sh
# =============================================================================
# 数据库初始化（幂等）：建库 → 执行 DDL → 补 Alembic 基线
#
# 为什么需要它：手动 `psql -f database/001_init.sql` 建库后，alembic_version 表为空，
# 之后 `alembic upgrade head` 会再次执行 0001 而报 "relation already exists"。
# 本脚本在建表后自动 `alembic stamp 0001_init`，把版本对齐到实际结构。
#
#   ./scripts/db-init.sh [库名]
# =============================================================================
set -eu

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

# 让非登录 shell 也能找到 Homebrew 装的 PostgreSQL（zsh 的 ~/.zshrc 不会在这些脚本里生效）
for _p in /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@16/bin; do
  if [ -d "$_p" ]; then case ":$PATH:" in *":$_p:"*) ;; *) PATH="$_p:$PATH" ;; esac; fi
done
export PATH


DB=${1:-freshkeep}
URL=${DATABASE_URL:-"postgresql+psycopg://$(whoami)@127.0.0.1:5432/$DB"}

command -v psql >/dev/null 2>&1 || {
  echo "⚠ psql 不可用。把它加进 PATH："
  echo '  echo '"'"'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"'"'"' >> ~/.zshrc'
  exit 1
}

echo "== 1/3 数据库 =="
if psql -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$DB"; then
  echo "库 $DB 已存在"
else
  createdb "$DB" && echo "已创建库 $DB"
fi

echo "== 2/3 表结构 =="
N=$(psql -d "$DB" -tAc "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")
if [ "$N" -eq 0 ]; then
  psql -d "$DB" -q -f database/001_init.sql
  echo "已执行 database/001_init.sql"
else
  echo "已有 $N 张表，跳过 DDL（如需重建：dropdb $DB && ./scripts/db-init.sh）"
fi

echo "== 3/3 Alembic 基线 =="
HAS=$(psql -d "$DB" -tAc "select (to_regclass('public.alembic_version') is not null)::text")
if [ -x backend/.venv/bin/alembic ]; then
  if [ "$HAS" = "true" ]; then
    echo -n "当前版本："
    (cd backend && DATABASE_URL="$URL" .venv/bin/alembic current 2>/dev/null | tail -1)
  else
    (cd backend && DATABASE_URL="$URL" .venv/bin/alembic stamp 0001_init 2>&1 | tail -1)
    echo "已补基线：0001_init（避免 upgrade 重复建表）"
  fi
else
  echo "⚠ backend/.venv 不存在，跳过 stamp。先跑 ./scripts/dev-setup.sh"
fi

echo
echo "验证：psql -d $DB -f database/002_acceptance_check.sql 2>&1 | grep NOTICE | tail -3"
echo "连接串：DATABASE_URL=$URL"
