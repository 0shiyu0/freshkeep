#!/bin/sh
# =============================================================================
# 安全迁移：先备份 → 再 alembic upgrade → 失败给出回滚点
#
#   ./scripts/migrate-safe.sh
# =============================================================================
set -eu

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

# 让非登录 shell 也能找到 Homebrew 装的 PostgreSQL（zsh 的 ~/.zshrc 不会在这些脚本里生效）
for _p in /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@16/bin; do
  if [ -d "$_p" ]; then case ":$PATH:" in *":$_p:"*) ;; *) PATH="$_p:$PATH" ;; esac; fi
done
export PATH


DB=${POSTGRES_DB:-freshkeep}
URL=${DATABASE_URL:-"postgresql+psycopg://$(whoami)@127.0.0.1:5432/$DB"}
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=backups
mkdir -p "$BACKUP_DIR"
DUMP="$BACKUP_DIR/pre-migrate-$DB-$STAMP.dump"

command -v pg_dump >/dev/null 2>&1 || { echo "⚠ pg_dump 不可用（PATH 里没有 postgresql@16/bin）"; exit 1; }

echo "== 1/3 备份 =="
pg_dump -d "$DB" -Fc -f "$DUMP"
SIZE=$(wc -c < "$DUMP" | tr -d ' ')
[ "$SIZE" -gt 1024 ] || { echo "备份文件异常（${SIZE} 字节），中止"; exit 1; }
echo "已备份 → ${DUMP}（${SIZE} 字节）"

echo "== 2/3 迁移 =="
BEFORE=$(psql -d "$DB" -tAc "select version_num from alembic_version" 2>/dev/null || echo "none")
echo "迁移前版本：$BEFORE"
if ! (cd backend && DATABASE_URL="$URL" .venv/bin/alembic upgrade head); then
  echo
  echo "❌ 迁移失败。回滚命令："
  echo "  pg_restore -d $DB --clean --if-exists $DUMP"
  echo "  （或删库重建：dropdb $DB && createdb $DB && pg_restore -d $DB ${DUMP}）"
  exit 1
fi

echo "== 3/3 校验 =="
AFTER=$(psql -d "$DB" -tAc "select version_num from alembic_version")
echo "迁移后版本：$AFTER"
psql -d "$DB" -f database/002_acceptance_check.sql 2>&1 | grep -c NOTICE | xargs -I{} echo "验收断言条数：{}"
echo "回滚点：$DUMP"
