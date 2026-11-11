#!/usr/bin/env bash
# 阶段 9 · NAS Docker 部署（可复现脚本，本身不含任何凭据）
#
# 前置：
#   - 本机可 ssh/scp 到 NAS（推荐配置 SSH key；若用密码，请通过 sshpass -f / SSH_ASKPASS 提供，
#     不要写进本脚本、源码或日志）
#   - NAS 用户能执行 sudo docker（本次部署用的是临时凭据文件，用完即删）
#   - NAS 已安装 Docker 28+ / Compose v2
#
# 用法：
#   NAS_HOST=192.168.31.198 NAS_USER=shiyu NAS_DIR=/vol1/docker/freshkeep \
#     ./scripts/deploy-nas.sh
#
# 本脚本只做：打包 → 上传 → 远端生成 .env（随机密码）与自签证书 → compose up。
# .env 与证书只存在于 NAS 上，不进入版本库。
set -euo pipefail
cd "$(dirname "$0")/.."

NAS_HOST="${NAS_HOST:?请设置 NAS_HOST}"
NAS_USER="${NAS_USER:-shiyu}"
NAS_DIR="${NAS_DIR:-/vol1/docker/freshkeep}"
NAS_IP="${NAS_IP:-$NAS_HOST}"
HTTP_PORT="${FK_HTTP_PORT:-18080}"
HTTPS_PORT="${FK_HTTPS_PORT:-18443}"
SUDO_FILE="${FK_SUDO_FILE:-/tmp/.fk_pw}"
BUNDLE="${TMPDIR:-/tmp}/freshkeep-deploy.tar.gz"
REMOTE="${NAS_USER}@${NAS_HOST}"

echo "[1/5] 打包（排除依赖、构建产物、备份、证书与 .env）"
tar czf "$BUNDLE" \
  --exclude='.git' --exclude='node_modules' --exclude='.venv' --exclude='frontend/dist' \
  --exclude='backups' --exclude='storage' --exclude='.pytest-backups' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='*.log' --exclude='*.pem' --exclude='.env' .
ls -lh "$BUNDLE"

echo "[2/5] 上传"
ssh "$REMOTE" "mkdir -p '$NAS_DIR'"
scp "$BUNDLE" "$REMOTE:$NAS_DIR/freshkeep-deploy.tar.gz"

echo "[3/5] 远端解压 + 生成 .env / 证书"
ssh "$REMOTE" "cd '$NAS_DIR' && tar xzf freshkeep-deploy.tar.gz && \
  umask 077 && python3 -c \"import secrets; print('POSTGRES_PASSWORD='+secrets.token_urlsafe(24))\" > .env && \
  chmod 600 .env && chmod +x scripts/gen-self-signed-cert.sh scripts/restore_drill.py && \
  bash scripts/gen-self-signed-cert.sh '$NAS_IP' >/dev/null && echo PREP_OK"

echo "[4/5] 构建并启动（HTTPS / 独立端口）"
ssh "$REMOTE" "cd '$NAS_DIR' && \
  FK_HTTP_PORT=$HTTP_PORT FK_HTTPS_PORT=$HTTPS_PORT \
  sudo -S -p '' docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build < '$SUDO_FILE' && \
  sudo -S -p '' docker compose -f docker-compose.yml -f docker-compose.https.yml ps < '$SUDO_FILE'"

echo "[5/5] 健康检查"
for u in "http://$NAS_HOST:$HTTP_PORT/health" "https://$NAS_HOST:$HTTPS_PORT/health"; do
  echo "  $u"
  curl -sk -o /dev/null -w '    HTTP %{http_code} · %{time_total}s\n' "$u" || true
done

cat <<EOF

部署完成：
  HTTP  http://${NAS_HOST}:${HTTP_PORT}/
  HTTPS https://${NAS_HOST}:${HTTPS_PORT}/ （自签证书，首次访问需信任）
  API   http://${NAS_HOST}:${HTTP_PORT}/api/v1/health

数据库迁移与字典种子由 api 容器 entrypoint 自动完成。
EOF
