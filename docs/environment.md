# 环境变量与运行环境

> 本文是**环境变量的唯一权威说明**。部署流程见 [DEPLOYMENT.md](DEPLOYMENT.md)，
> 备份见 [BACKUP_RESTORE.md](BACKUP_RESTORE.md)，回滚见 [ROLLBACK.md](ROLLBACK.md)，
> 本机安装排障见 [environment.md](environment.md)。

## 1. 配置加载顺序

后端配置集中在 `backend/app/core/config.py`（dataclass，启动时读一次环境变量）：

```
进程环境变量  >  docker-compose.yml 的 environment  >  .env 文件（compose 自动读取）  >  代码内默认值
```

- `.env` **不进版本库**（见 `.gitignore`），模板是 [`.env.example`](../.env.example)。
- 修改 `.env` 后必须 `docker compose up -d`（重建容器）才生效；只 `restart` 不会重读文件。

## 2. 变量清单

### 2.1 必填

| 变量 | 示例 | 作用 | 备注 |
| --- | --- | --- | --- |
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` | PostgreSQL 与 api 的连接密码 | compose 用 `${POSTGRES_PASSWORD:?}` 强制校验；**pgdata 首次初始化后改它会导致 api 连不上库** |

### 2.2 数据库

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `POSTGRES_DB` | `freshkeep` | 库名 |
| `POSTGRES_USER` | `freshkeep` | 库用户，同时用于拼 `DATABASE_URL` |
| `DATABASE_URL` | 由上两项 + 密码拼出 | 后端连接串；不用 compose 单独部署时必填 |
| `DB_POOL_SIZE` | `5` | 连接池常驻连接数 |
| `DB_MAX_OVERFLOW` | `10` | 峰值可额外开的连接数 |
| `DB_POOL_TIMEOUT` | `10` | 取连接超时（秒） |
| `DB_POOL_RECYCLE` | `1800` | 连接回收周期（秒），防止被中间设备掐断 |
| `DB_ECHO` | `0` | `1` 时打印所有 SQL（调试用，生产勿开） |

### 2.3 应用与日志

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `APP_NAME` | `freshkeep` | 应用名（日志与 OpenAPI 标题） |
| `APP_ENV` | `dev` | 环境标识（`dev` / `prod`），影响日志与错误细节 |
| `HOST` | `0.0.0.0` | 监听地址（容器内） |
| `PORT` | `8000` | api 监听端口（容器内，不对外） |
| `WORKERS` | `2` | uvicorn 进程数；**每个进程都会各自启动一份 APScheduler**，单用户场景建议 ≤2 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_JSON` | `true` | `true` 单行 JSON（便于采集）；`false` 可读文本 |
| `ACCESS_LOG` | `true` | 是否记录访问日志 |
| `LOG_DIR` | 容器 `/data/logs`；本机 `storage/logs` | 日志目录 |
| `DATA_DIR` | 仓库根 | 数据目录基准 |
| `STORAGE_DIR` | `/data/storage` | 上传/导出文件目录 |
| `BACKUP_DIR` | `/data/backups` | 逻辑备份目录 |
| `SERVE_STATIC` | `0` | `1` 时由 api 托管前端（本项目用 nginx，保持 `0`） |
| `STATIC_DIR` | `frontend/dist` | 上者为 1 时的静态目录 |
| `TRUST_PROXY` | `0` | 在反向代理后置 `1`，读取真实客户端 IP |

### 2.4 鉴权

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `TOKEN_TTL_DAYS` | `30` | 设备访问令牌有效期（天） |
| `PAIR_CODE_TTL_MINUTES` | `10` | 配对码有效期（分钟），一次性 |

### 2.5 网络边界与跨源

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `ALLOW_CIDR` | `192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10,127.0.0.1/32` | 允许访问的网段；**公网暴露前必须收紧** |
| `CORS_ORIGINS` | `capacitor://localhost,http://localhost,http://localhost:5173` | 允许的跨源来源（原生 App 的 WebView origin） |

### 2.6 定时任务与备份

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `ENABLE_SCHEDULER` | 代码内 `false`，compose 设 `true` | 是否启动 APScheduler（03:00 对账 / 03:10 备份 / 08:00 扫描） |
| `BACKUP_KEEP` | `7` | 逻辑备份保留份数，超出按时间删旧 |

### 2.7 时区

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 容器系统时区 |
| `TZ_BIZ` | `Asia/Shanghai` | 业务日期口径（“今天”“临期 N 天”都基于它） |

### 2.8 端口（compose 层，不传给应用）

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `HOST_PORT` | `8080` | 仅用 `docker-compose.yml` 时的对外 HTTP 端口 |
| `FK_HTTP_PORT` | `18080` | 用 `docker-compose.https.yml` 时的 HTTP 端口 |
| `FK_HTTPS_PORT` | `18443` | 同上，HTTPS 端口 |

> compose 的 `ports` 是**追加合并**：`docker-compose.https.yml` 必须用 `ports: !override` 覆盖 base 的 8080，
> 否则两个端口会同时绑定，8080 被占用时直接启动失败。

## 3. 环境矩阵

| 项 | 本地开发 | NAS 生产（base + https override） |
| --- | --- | --- |
| 入口 | `http://localhost:8080` | `https://<NAS_IP>:18443`（自签证书） |
| 对外端口 | 8080 → web:80 | 18080 → web:80、18443 → web:443 |
| 数据库 | compose 内 `db:5432` | 同左，仅内网 |
| 数据目录 | 仓库 `./pgdata`、`./storage`、`./backups` | `/vol1/docker/freshkeep/{pgdata,storage,backups}` |
| `.env` | 手动 `cp .env.example .env` 填密码 | 部署脚本在 NAS 上随机生成 |
| 证书 | 可选 | 必备（SAN 填 NAS IP） |
| 定时任务 | compose 已设 `true` | 同左 |

## 4. 本地开发（不跑容器）

```bash
# 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://<本机用户>@127.0.0.1:5432/freshkeep"
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest          # 232 项 + 覆盖率门槛 80%

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5173
```

测试库 `freshkeep_test` 由 `tests/conftest.py` 自动创建并每次重建（从 `database/001_init.sql` 建表），
`alembic_version` 写入**当前迁移 head**（不再硬编码）。

安装排障（Homebrew 装 PG、pip 镜像、Docker/Xcode 路径）见 [environment.md](environment.md)。

## 5. 常见配置错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `请在 .env 里设置 POSTGRES_PASSWORD` | `.env` 缺失或密码为空 | 填随机串 |
| `password authentication failed for user "freshkeep"` | pgdata 已初始化，`.env` 密码后来被改 | `docker exec freshkeep-db psql -U freshkeep -c "ALTER USER freshkeep WITH PASSWORD '<新密码>'"` |
| `Bind for 0.0.0.0:8080 failed` | base 与 override 同时绑定端口 | 确认 override 用 `ports: !override`，或改 `HOST_PORT` |
| 页面能开但接口 403/超时 | 客户端不在 `ALLOW_CIDR` 内 | 补充网段 |
| 时间判断差 8 小时 | `TZ`/`TZ_BIZ` 未设 | 两者都设 `Asia/Shanghai` |
| 容器重启后任务没按点跑 | APScheduler 是进程内作业，重启重新注册、不补跑 | 需要严格准点就改用外部 cron 调 `POST /tasks/{id}/run` |
