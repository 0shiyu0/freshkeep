#!/bin/sh
# 鲜度 FreshKeep · 恢复脚本（危险操作，执行前会二次确认）
#   ./deploy/restore.sh data/backups/freshkeep-20261108-030000.dump
set -eu

if [ $# -lt 1 ]; then
  echo "用法：$0 <dump 文件路径>" >&2
  exit 1
fi
DUMP=$1
[ -f "$DUMP" ] || { echo "文件不存在：$DUMP" >&2; exit 1; }

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ -f .env ]; then
  # shellcheck disable=SC1091
  . ./.env
fi
DB_USER=${POSTGRES_USER:-freshkeep}
DB_NAME=${POSTGRES_DB:-freshkeep}

echo "即将用 $DUMP 覆盖数据库 $DB_NAME。"
echo "恢复会丢弃当前全部数据，建议先跑一次 ./deploy/backup.sh。"
printf "输入 YES 继续："
read -r ANSWER
[ "$ANSWER" = "YES" ] || { echo "已取消"; exit 1; }

echo "[restore] 停 api（避免写入）"
docker compose stop api

echo "[restore] 重建数据库"
docker compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE);" \
  -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

echo "[restore] 导入 dump"
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner < "$DUMP"

echo "[restore] 启动 api"
docker compose start api

echo "[restore] 完成。请打开网页确认库存与流水一致。"
