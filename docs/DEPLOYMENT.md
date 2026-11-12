# 部署到 NAS（fnOS / 群晖 / 任意 Linux Docker）

> 环境变量含义见 [ENVIRONMENT.md](ENVIRONMENT.md)；备份与恢复见 [BACKUP_RESTORE.md](BACKUP_RESTORE.md)；
> 升级失败怎么退回见 [ROLLBACK.md](ROLLBACK.md)。

## 0. 目标形态

三个容器，只有 `web` 对外暴露：

| 容器 | 镜像 | 端口 | 对外 |
| --- | --- | --- | --- |
| `freshkeep-web` | 本项目构建（nginx + 前端产物） | 80 / 443 | ✅ 18080 / 18443 |
| `freshkeep-api` | 本项目构建（FastAPI + APScheduler） | 8000 | ❌ 仅内网 |
| `freshkeep-db` | `postgres:16-alpine` | 5432 | ❌ 仅内网 |

数据全部落 bind mount：`./pgdata`（数据库）、`./storage`（上传/日志）、`./backups`（逻辑备份）。
**容器重建、镜像升级都不影响这三处数据。**

## 1. 前置检查

```bash
# 在 NAS 上
docker --version            # 需要 24+
docker compose version      # 需要 v2.24+（用到 ports: !override）
curl -s https://api.github.com > /dev/null && echo "外网可达" || echo "外网受限"

# 端口占用检查（18080 / 18443 必须空闲）
ss -ltn | grep -E ":18080|:18443" || echo "端口空闲"
```

目录建议放在存储卷上（不要放系统盘 `/tmp`，重启会丢）：

```bash
sudo mkdir -p /vol1/docker/freshkeep
sudo chown -R "$USER":"$(id -gn)" /vol1/docker/freshkeep
```

## 2. 方式 A：NAS 能直接构建（推荐，后续升级最简单）

```bash
cd /vol1/docker/freshkeep
git clone https://github.com/0shiyu0/freshkeep.git .
cp .env.example .env
# 生成随机密码并写入 .env（不要手输固定值）
sed -i.bak "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')|" .env
chmod 600 .env

# HTTPS（自签，SAN 填 NAS 的内网 IP）
./scripts/gen-self-signed-cert.sh 192.168.31.198

# 构建并启动
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

首次构建约 3~6 分钟（取决于网络，Dockerfile 已内置清华 pip 源与 npmmirror）。

## 3. 方式 B：NAS 拉不到镜像 / 架构不同（当前线上采用）

典型情况：NAS 是 x86_64，开发机是 Apple Silicon；或 NAS 的 registry 代理返回 401。

```bash
# ① 在开发机构建 amd64 镜像（不要用默认架构，否则 NAS 上跑不起来）
docker buildx build --platform linux/amd64 --load \
  -t freshkeep-api:amd64 -f backend/Dockerfile .
docker buildx build --platform linux/amd64 --load \
  -t freshkeep-web:amd64 -f frontend/Dockerfile ./frontend

# ② 导出并压缩（约 94MB）
docker save freshkeep-api:amd64 freshkeep-web:amd64 -o /tmp/fk_images.tar
gzip -f -1 /tmp/fk_images.tar

# ③ 传到 NAS 并载入
scp /tmp/fk_images.tar.gz <user>@<nas>:/vol1/docker/freshkeep/
ssh <user>@<nas>
cd /vol1/docker/freshkeep
docker load -i fk_images.tar.gz
docker tag freshkeep-api:amd64 freshkeep-api:latest
docker tag freshkeep-web:amd64 freshkeep-web:latest

# ④ 起服务（-f 顺序固定：base 在前，override 在后）
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate

# ⑤ 清理临时包（约 200MB）
rm -f fk_images.tar.gz
```

**两个必须注意的点**（都实际踩过）：

1. `docker compose up -d` **不会因为镜像 ID 变化而重建容器**（它比的是 compose 配置）。
   载入新镜像后必须加 `--force-recreate`，否则跑的还是旧代码。
2. `sudo docker compose ...` 会重置环境变量，`FK_HTTP_PORT` 之类的值读不到。
   **端口写进 `.env` 文件**，不要靠命令行前缀传。

## 4. 首次部署验证

```bash
cd /vol1/docker/freshkeep
docker compose -f docker-compose.yml -f docker-compose.https.yml ps

# 期望：三个容器都是 (healthy)
curl -s -o /dev/null -w "HTTP  %{http_code}\n" http://127.0.0.1:18080/health
curl -sk -o /dev/null -w "HTTPS %{http_code}\n" https://127.0.0.1:18443/health

# PWA 资产
for p in /manifest.webmanifest /sw.js /offline.html /icons/icon-192.png; do
  curl -sk -o /dev/null -w "  $p %{http_code}\n" "https://127.0.0.1:18443$p"
done

# 数据库版本（应等于仓库最新迁移）
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
```

浏览器打开 `https://<NAS_IP>:18443` → 首屏会出现证书警告（自签），信任后进入配对页。
配对码在 NAS 上生成：

```bash
docker exec freshkeep-api python -m app.cli pair    # 6 位，10 分钟有效，一次性
```

**验收清单**（8 项，全过即部署成功）：

- [ ] 三容器 `healthy`，无重启循环（`docker ps` 的 STATUS 不显示 `Restarting`）
- [ ] `HTTP /health` 与 `HTTPS /health` 均 200
- [ ] PWA 四个资产均 200
- [ ] 浏览器能打开首页，控制台无报错
- [ ] 配对码可登录，刷新后仍保持登录
- [ ] 新增一个食材 + 入库一批，`/inventory` 能看到
- [ ] 设置页「立即备份」成功，`./backups/` 出现新文件
- [ ] 重启容器（`docker compose restart`）后数据仍在

## 5. 升级

**升级前必须备份**（见 [BACKUP_RESTORE.md](BACKUP_RESTORE.md) 的 §2），再选一种方式：

### 5.1 方式 A（git + 构建）

```bash
cd /vol1/docker/freshkeep
./deploy/backup.sh                                   # 先备份
git fetch --tags && git checkout v1.0.0              # 切到目标版本
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
docker compose logs --tail=50 api | grep -i alembic  # 确认迁移已执行
```

### 5.2 方式 B（导入镜像）

```bash
docker load -i freshkeep-v1.0.0-amd64.tar.gz
docker tag freshkeep-api:1.0.0 freshkeep-api:latest
docker tag freshkeep-web:1.0.0 freshkeep-web:latest
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate
```

### 5.3 升级后检查

```bash
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1:18443/health
docker compose logs --tail=20 api | grep -E "ERROR|Traceback" || echo "无错误"
```

数据库迁移由 api 容器的 `entrypoint.sh` 自动执行（`alembic upgrade head`），不需要手工跑。
**降级不自动回滚数据库**，需要按 [ROLLBACK.md](ROLLBACK.md) 恢复备份。

## 6. 端口与防火墙

- 只开 18080 / 18443，**不要**把 8000、5432 映射出去。
- 若用 fnOS / 群晖的反向代理，注意透传 `X-Forwarded-Proto`，并在 `.env` 设 `TRUST_PROXY=1`。
- `ALLOW_CIDR` 默认只放行内网网段；公网暴露前必须收紧并只保留 18443。

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `dependency failed to start: container freshkeep-api is unhealthy` | api 连不上库（密码不一致 / db 未就绪） | 看 `docker logs freshkeep-api`；密码问题见 [ENVIRONMENT.md](ENVIRONMENT.md) §5 |
| `Bind for 0.0.0.0:8080 failed` | base 与 override 端口同时绑定 | 确认 `docker-compose.https.yml` 用 `ports: !override` |
| `exec format error` | 镜像架构与 NAS 不符（arm64 镜像跑在 x86 上） | 用 `buildx --platform linux/amd64` 重建 |
| `failed to resolve source metadata ... 401` | NAS 的 registry 代理需要鉴权 | 用 §3 方式 B 导入镜像，不要改 NAS 全局 Docker 配置 |
| api 日志反复 `password authentication failed` | pgdata 已初始化，`.env` 密码后来改过 | `ALTER USER` 对齐密码，不要删 pgdata |
| 升级后新接口 404 | 容器没重建（旧镜像） | `up -d --force-recreate` |
| 容器日志占满磁盘 | 未配日志轮转 | 本项目 compose 已配 `max-size: 10m / max-file: 3` |

## 8. 卸载（保留数据）

```bash
cd /vol1/docker/freshkeep
docker compose -f docker-compose.yml -f docker-compose.https.yml down   # 只停容器，不删数据
# pgdata / storage / backups 仍在磁盘上，可随时用同一 compose 再起来
```

⚠ **绝不要用 `docker compose down -v`**：本项目数据是 bind mount，`-v` 只会删命名卷，
真正的风险是有人误以为数据在卷里而直接 `rm -rf pgdata`。删除目录前先做备份。
