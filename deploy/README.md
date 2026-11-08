# deploy/ · NAS 部署手册

目标环境：飞牛 fnOS（或任意 Linux）+ Docker Compose v2。整个系统只有两个容器：`db` 与 `api`。

---

## 1. 前置检查

| 项 | 要求 | 检查命令 |
| --- | --- | --- |
| Docker | 24+，Compose v2 | `docker compose version` |
| 内存 | ≥ 1 GB 可用（PG 约 150 MB、api 约 150 MB） | `free -m` |
| 磁盘 | ≥ 2 GB（镜像 + 数据库 + 备份） | `df -h` |
| 端口 | 8080 空闲 | `ss -lntp \| grep 8080` |
| 权限 | 能把目录 chown 给容器用户 | — |

---

## 2. 首次部署

```bash
# 1) 建目录（按你的存储卷名调整；示例为 /vol2）
mkdir -p /vol2/docker/food-manager/{pgdata,data,data/backups}
cd /vol2/docker/food-manager

# 2) 取代码
git clone git@github.com:0shiyu0/freshkeep.git .

# 3) 配置环境变量（必须改密码）
cp .env.example .env
sed -i '' "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -base64 24)|" .env   # macOS
# Linux 用：sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -base64 24)|" .env

# 4) 构建并启动（首次会装依赖 + 跑迁移，约 3~5 分钟）
docker compose up -d --build

# 5) 看健康状态
docker compose ps
curl -s http://127.0.0.1:8080/health
```

`/health` 期望返回 `{"status":"ok","db":true,"version":"0.1.0"}`。

> 迁移由 `api` 容器的入口脚本自动执行（`alembic upgrade head`），无需手动建表。
> 若想手动确认：`docker compose exec api alembic current` 应显示 `0001_init (head)`。

---

## 3. 首次配对（生成设备令牌）

```bash
docker compose exec api python -m app.cli pair
# 输出：配对码 4K7T2M（10 分钟内有效，一次性）
```

- **Web**：浏览器打开 `http://<NAS_IP>:8080` → 跳到配对页 → 输入码 → 得到 HttpOnly Cookie。
- **App**：首次启动填 `http://<NAS_IP>:8080` → 输入码 → 令牌存 Keychain/Keystore。

设备一旦授权**长期有效**，可在「设置 → 已授权设备」查看与吊销。手机丢了就吊销那一台。

---

## 4. 网络边界（重要）

本项目**不做公网暴露**，三条同时成立才算配置正确：

1. 路由器上**不要**做 8080 的端口映射；
2. NAS 防火墙只放行内网与组网网段；
3. `.env` 里的 `ALLOW_CIDR` 保持默认（含 `192.168.0.0/16`、`10.0.0.0/8`、`100.64.0.0/10` 等）。

外网访问用异地组网（Tailscale / ZeroTier），手机连上组网后填组网 IP（如 `100.x.y.z:8080`）。

---

## 5. 日常运维

```bash
docker compose ps                  # 状态
docker compose logs -f api         # 日志
docker compose restart api         # 重启
docker compose down                # 停止（数据在 pgdata/ 里，不会丢）
```

### 备份（建议每天一次）

```bash
./deploy/backup.sh
```

产物在 `data/backups/`：`freshkeep-<时间>.dump` + `files-<时间>.tar.gz`，保留最近 14 份。
NAS 计划任务里加一条：

```
0 3 * * * cd /vol2/docker/food-manager && ./deploy/backup.sh >> data/backups/backup.log 2>&1
```

### 恢复

```bash
./deploy/restore.sh data/backups/freshkeep-20261108-030000.dump
```

脚本会二次确认、停 api、重建库、导入、再启动。**每季度演练一次**，确认备份真的能用。

---

## 6. 升级

```bash
cd /vol2/docker/food-manager
./deploy/backup.sh            # 先备份
git pull
docker compose up -d --build  # 重建 api，迁移自动执行
docker compose logs -f api    # 确认启动正常
```

数据库结构变更只在 `database/001_init.sql` 里改；已有数据的库需要新迁移（见 `AGENTS.md` §5）。

---

## 7. 排障

| 现象 | 排查 |
| --- | --- |
| `api` 反复重启 | `docker compose logs api`；多为 `POSTGRES_PASSWORD` 为空或 `db` 未 healthy |
| `/health` 返回 `db:false` | `docker compose exec db pg_isready -U freshkeep`；检查 `.env` 密码与 `pgdata` 权限 |
| 网页 404 / 白屏 | `frontend/dist` 未构建：`cd frontend && npm ci && npm run build`，再 `docker compose restart api` |
| 配对码无效 | 已过期（10 分钟）或用过；重新执行 `python -m app.cli pair` |
| 手机连不上但电脑能开 | 手机不在同一网段、未连组网，或源 IP 不在 `ALLOW_CIDR` |
| App 白屏 | 未配 `usesCleartextTraffic` / ATS 例外 / `androidScheme:'http'`（见 `final-plan.md` §3.3） |
| 备份文件很小 | 检查 `POSTGRES_PASSWORD` 是否为空导致 `pg_dump` 失败（脚本已有 1 KB 下限保护） |

---

## 8. 安全清单（上线前逐条打勾）

- [ ] `.env` 里 `POSTGRES_PASSWORD` 是随机串，不是默认值
- [ ] 路由器无 8080 端口映射
- [ ] `ALLOW_CIDR` 未放宽到 `0.0.0.0/0`
- [ ] `pgdata/` 与 `data/` 不进版本库（`.gitignore` 已含）
- [ ] 备份目录不在容器内（避免容器重建丢备份）
- [ ] 已记录每个已授权设备，废弃设备已吊销
