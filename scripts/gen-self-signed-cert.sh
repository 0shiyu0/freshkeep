#!/usr/bin/env bash
# 阶段 9 · 生成家庭内网自签证书（不入库）。
# 用法：./scripts/gen-self-signed-cert.sh [NAS_IP]
# 产物：storage/certs/freshkeep.crt / freshkeep.key（chmod 600）
set -euo pipefail
cd "$(dirname "$0")/.."
IP="${1:-192.168.31.198}"
OUT="storage/certs"
mkdir -p "$OUT"

if [ -f "$OUT/freshkeep.crt" ] && [ -f "$OUT/freshkeep.key" ]; then
  echo "证书已存在：$OUT/freshkeep.crt（如需轮换先删除）"
  exit 0
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 3650 -sha256 \
  -keyout "$OUT/freshkeep.key" -out "$OUT/freshkeep.crt" \
  -subj "/C=CN/O=FreshKeep Home/CN=freshkeep.local" \
  -addext "subjectAltName=DNS:freshkeep.local,DNS:localhost,IP:${IP},IP:127.0.0.1" \
  >/dev/null 2>&1
chmod 600 "$OUT/freshkeep.key"
chmod 644 "$OUT/freshkeep.crt"

echo "已生成自签证书（SAN 含 ${IP} / freshkeep.local / localhost）："
openssl x509 -in "$OUT/freshkeep.crt" -noout -subject -dates -ext subjectAltName
cat <<'EOF'

说明：这是家庭内网自签证书，浏览器首次访问会提示「不受信任」，
需在客户端信任该证书（或导入系统钥匙串）。它不是公网 CA 证书。
EOF
