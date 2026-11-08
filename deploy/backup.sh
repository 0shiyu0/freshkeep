#!/bin/sh
# 鲜度 FreshKeep · 备份脚本（在 NAS 上、项目根目录执行）
#   ./deploy/backup.sh
# 环境变量：BACKUP_KEEP（默认 14）、COMPOSE_FILE（默认 docker-compose.yml）
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

KEEP=${BACKUP_KEEP:-14}
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$ROOT/data/backups"
mkdir -p "$DEST"

# 从 .env 读数据库名与用户
if [ -f .env ]; then
  # shellcheck disable=SC1091
  . ./.env
fi
DB_USER=${POSTGRES_USER:-freshkeep}
DB_NAME=${POSTGRES_DB:-freshkeep}

echo "[backup] 导出数据库 → $DEST/freshkeep-$STAMP.dump"
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DEST/freshkeep-$STAMP.dump"

echo "[backup] 打包文件资源 → $DEST/files-$STAMP.tar.gz"
if [ -d "$ROOT/data/files" ]; then
  tar -czf "$DEST/files-$STAMP.tar.gz" -C "$ROOT/data" files
else
  echo "[backup] 跳过：暂无 data/files 目录"
fi

# 完整性：dump 至少要有几 KB，否则视为失败（避免留下空备份占位）
SIZE=$(wc -c < "$DEST/freshkeep-$STAMP.dump" | tr -d ' ')
if [ "$SIZE" -lt 1024 ]; then
  echo "[backup] 失败：dump 只有 ${SIZE} 字节" >&2
  rm -f "$DEST/freshkeep-$STAMP.dump"
  exit 1
fi

# 只保留最近 KEEP 份
ls -1t "$DEST"/freshkeep-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r f; do
  echo "[backup] 清理旧备份 $(basename "$f")"
  rm -f "$f"
done
ls -1t "$DEST"/files-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r f; do
  rm -f "$f"
done

echo "[backup] 完成：$DEST/freshkeep-$STAMP.dump（${SIZE} 字节，保留最近 $KEEP 份）"
