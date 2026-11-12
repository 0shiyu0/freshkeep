# 鲜度 FreshKeep · 家庭食材库存与营养管理

> 自托管 · 批次级库存 · 成本核算 · 营养估算 · 临期提醒 · 原生 App

一套跑在自己 NAS 上的家庭食材管理应用：记录买回来什么、先到期先消耗、每天取用自动扣减，
顺便算出这一餐花了多少钱、摄入了多少营养。**数据不出家门。**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-22-339933?logo=node.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)

**当前状态**：功能开发完成（阶段 0~9 + M0~M10），正在做 V1.0.0 发布准备。
后端测试 **232 passed**；数据库 **27 张表 + 2 个视图**；迁移版本 `0004_recipe_steps`。

---

## 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Naive UI | 单页应用，移动优先；PWA 可安装、离线可看已缓存页面 |
| 后端 | FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 | 分层：`api/v1`（HTTP）→ `services`（业务）→ `models`（ORM） |
| 数据库 | PostgreSQL 16 | 金额/重量用 `NUMERIC` 定点存储，**全程不出现浮点** |
| 部署 | Docker Compose（db / api / web 三容器） | web 用 nginx 托管前端并反代 `/api` |
| 原生 | Capacitor 8（Android + iOS，SPM 模式） | WebView 加载打包前端，直连 NAS 内网地址 |

## 功能模块

| 模块 | 能力 |
| --- | --- |
| **食材档案** | 分类 / 单位（含数量↔重量换算）/ 存放位置 / 条码 / 图片 / 营养基准 |
| **批次库存** | 一次采购一个批次，FEFO（先到期先出）自动分配；批次可部分消耗 |
| **消耗与流水** | 每次取用生成流水与批次分配，可撤销；成本按实际分配重量计算 |
| **盘点与报损** | 盘盈盘亏、丢弃都留痕，不允许静默改数 |
| **临期提醒** | 已过期 / N 天内 / 本周到期三段；应用内通知中心（不做系统级推送） |
| **营养管理** | 营养项目、档案版本、快照、四周期达标率、来源追溯 |
| **统计看板** | 趋势、占比、排行、周转；成本与浪费口径分离 |
| **采购建议** | 低于最低库存自动建议；可一键生成采购清单 |
| **菜谱** | 步骤结构化（可带单步时长）、按份数缩放匹配库存、多菜谱合并缺口 |
| **采购清单** | 缺口合并、勾选完成、按低库存生成、**一键入库**（逐项走五步事务） |
| **扫码与识别** | 摄像头扫码 + 本地条码库 + 可配置外部商品源；AI 识别**只写草稿表**，人工确认后才建档 |
| **备份与运维** | 逻辑备份（schema + CSV + manifest）、CSV 导出、定时对账/备份/扫描、恢复演练 |

## 架构

```
        ┌──────────── 浏览器 / PWA / Android / iOS ────────────┐
        │                                                      │
        ▼                                                      ▼
┌──────────────────┐                              ┌────────────────────┐
│  web (nginx)     │   /api/* 反向代理             │  外部商品条码源     │
│  静态前端 + 反代  │ ───────────────────────────► │  （可选，可关闭）    │
└────────┬─────────┘                              └────────────────────┘
         │
         ▼
┌──────────────────┐        ┌──────────────────────┐
│  api (FastAPI)   │───────►│  db (PostgreSQL 16)  │
│  业务 / 定时任务  │        │  27 表 + 2 视图       │
└────────┬─────────┘        └──────────────────────┘
         │
         ▼
  storage/（上传、导出、日志）  backups/（逻辑备份）
```

三个容器只有 `web` 对外暴露端口；`api` 与 `db` 仅在 compose 内网可达。
应用层还有网段白名单（`ALLOW_CIDR`）与幂等中间件。

## 目录结构

```
freshkeep/
├── backend/
│   ├── app/
│   │   ├── api/v1/         # HTTP 层：只做参数校验 + 调 service + 包装响应
│   │   ├── services/       # 业务层：库存引擎、消耗、菜谱、识别、备份…
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── schemas/        # Pydantic 请求/响应模型
│   │   ├── core/           # 配置、日志、错误、中间件
│   │   └── tasks/          # APScheduler：对账 / 备份 / 扫描
│   ├── migrations/versions # Alembic 迁移 0001~0004（DDL 真相在 database/001_init.sql）
│   ├── tests/              # pytest：acceptance / api / unit
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/          # 17 个视图
│   │   ├── api/            # 类型化 API 客户端
│   │   ├── stores/         # Pinia
│   │   ├── utils/          # 通知、日志、格式化
│   │   └── styles/
│   ├── public/             # PWA：manifest、sw.js、offline.html、icons
│   ├── android/            # Capacitor Android 工程（cleartext + CAMERA 已配）
│   ├── ios/                # Capacitor iOS 工程（SPM，无 Podfile）
│   ├── Dockerfile
│   ├── nginx.conf          # HTTP（本地/内网）
│   └── nginx.https.conf    # 80 + 443，HSTS/CSP 等安全头
├── database/               # 001_init.sql（DDL 唯一真相）+ 002 验收自检
├── deploy/                 # 宿主机备份/恢复脚本 + 部署说明
├── scripts/                # session-start / status-snapshot / migrate-safe / deploy-nas
│                           # / restore_drill / stage9_acceptance / gen-self-signed-cert
├── docs/                   # PRD、架构、开发计划、状态、变更、API、数据库、ER 图、报告
├── legacy/                 # 早期纯静态版归档（不参与构建，仅作交互参考）
├── docker-compose.yml      # 三容器（HTTP-only）
└── docker-compose.https.yml# 端口覆盖 + HTTPS 证书挂载
```

运行时数据 `pgdata/`、`storage/`、`backups/` 都在 `.gitignore` 内，**不会进仓库**。

## 快速开始（本地）

```bash
git clone https://github.com/0shiyu0/freshkeep.git
cd freshkeep
cp .env.example .env          # 必须填 POSTGRES_PASSWORD（openssl rand -base64 24）
docker compose up -d --build  # 首次构建约 2~4 分钟
```

打开 <http://localhost:8080>，用配对码登录：

```bash
docker compose exec api python -m app.cli pair   # 输出 6 位配对码，10 分钟内有效
```

`api` 容器启动时会自动执行 `alembic upgrade head` 与字典种子，不需要手工初始化。

想用 HTTPS（自签证书）：

```bash
./scripts/gen-self-signed-cert.sh <你的内网IP>
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
# HTTP :18080 / HTTPS :18443
```

## 部署到 NAS

`scripts/deploy-nas.sh` 覆盖完整链路：打包 → 上传 → 远端生成 `.env` 与自签证书 → compose 启动。
脚本本身不含任何凭据；`.env` 与证书只存在 NAS 上。

```bash
NAS_HOST=192.168.31.198 NAS_USER=shiyu NAS_DIR=/vol1/docker/freshkeep \
  FK_SUDO_FILE=/tmp/.sudo_pw ./scripts/deploy-nas.sh
```

跨架构（Apple Silicon → x86 NAS）时先用 `buildx --platform linux/amd64` 构建并 `docker save/load` 导入，
详见 [deploy/README.md](deploy/README.md)。

## 数据、备份与恢复

| 内容 | 容器内 | 宿主机 |
| --- | --- | --- |
| 数据库 | `/var/lib/postgresql/data` | `./pgdata` |
| 上传与导出 | `/data/storage` | `./storage` |
| 应用日志 | `/data/logs` | `./storage/logs` |
| 逻辑备份 | `/data/backups` | `./backups` |

- **自动备份**：`ENABLE_SCHEDULER=true` 时每天 03:10 生成 `freshkeep-backup-<时间戳>.tar.gz`
  （`schema.sql` + 27 张表 CSV + `manifest.json`），只保留最近 `BACKUP_KEEP`（默认 7）份。
- **手工导出**：`GET /api/v1/export/transactions.csv`、`/consumptions.csv`（带 BOM，Excel 直接打开）。
- **恢复演练**：`python3 scripts/restore_drill.py` —— 备份恢复到临时库、逐表核对行数、结束后删库，
  不触碰生产库。记录见 [docs/reports/restore-drill.md](docs/reports/restore-drill.md)。
- **物理备份**：`deploy/backup.sh` / `deploy/restore.sh` 用 `pg_dump -Fc`。

## 开发

```bash
# 后端测试（232 项）
cd backend && .venv/bin/python -m pytest

# 前端构建
cd frontend && npm install && npm run build

# 迁移（结构变更只改 database/001_init.sql，迁移仅登记版本）
cd backend && alembic upgrade head

# 会话状态自检（Git / 迁移 / 测试 / 文档一致性）
./scripts/session-start.sh
```

**约定**：DDL 的唯一真相是 `database/001_init.sql`；Alembic 迁移不另写 DDL。
金额与重量一律 `Decimal` / `NUMERIC`，禁止浮点。分层铁律见 [AGENTS.md](AGENTS.md)。

## 安全

- `.env`、证书、数据库数据、上传文件、备份**全部**在 `.gitignore` 内；仓库不含任何真实凭据。
- 网段白名单默认只允许局域网与组网网段；`api` / `db` 不对宿主机暴露端口。
- HTTPS 版本带 HSTS、CSP、X-Frame-Options、nosniff、Referrer-Policy。
- 自签证书仅用于内网；公网访问请换 CA 证书并配置域名。
- 完整审计结论见 [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 开发规则：技术栈、分层、Decimal 铁律、禁止事项 |
| [docs/PRD.md](docs/PRD.md) | 产品需求、业务规则、验收用例 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、数据模型、API 规范、核心算法、ADR |
| [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | 阶段 0 + M0~M10 的任务与完成判据 |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | 当前进度、证据、已知问题 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 变更记录（含每次数据库结构变化） |
| [docs/api.md](docs/api.md) · [docs/database.md](docs/database.md) · [docs/er-diagram.md](docs/er-diagram.md) | 接口清单 / 表结构 / ER 图 |

## 许可证

[MIT](LICENSE)。第三方依赖以 MIT / BSD / Apache-2.0 为主，含一个 LGPL-3.0 运行时依赖（`psycopg`，
以库形式动态使用、未修改）；详见 [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md)。

`legacy/` 是项目早期纯静态版（localStorage 方案）的归档，**不参与任何构建与部署**，仅供交互参考。
