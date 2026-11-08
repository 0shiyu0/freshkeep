# 变更记录

格式参考 Keep a Changelog：`新增 / 变更 / 修复 / 移除 / 数据库 / 文档`。
每次提交若涉及数据库变化，必须在「数据库」小节写明表、字段、索引的增删改，以及是否需要重建或迁移。

---

## 2026-11-09 · 阶段 1：项目初始化

### 新增

- **三容器架构**：`db`（PostgreSQL 16）/ `api`（FastAPI，容器内 8000，不对外）/ `web`（nginx 托管 dist 并反代 `/api`，对外 8080）。
- `frontend/Dockerfile`（node 构建 → nginx）、`frontend/nginx.conf`（gzip、静态长缓存、SPA 回退、`/api` 反代、`/health` 透传）。
- 后端：`core/logging.py`（JSON/纯文本双格式、按 request_id 串联、滚动文件）、`api/v1/system.py`
  （`/health`、`/ping`、`/system/db`、`/system/client-logs`）、`api/v1/router.py`、连接池参数化。
- 前端：`api/http.ts`（Axios 实例 + 请求 id + 统一错误 + 401 出口）、`api/index.ts`、
  `utils/logger.ts`（全局异常捕获 + 批量上报）、`utils/notify.ts`（Naive UI 离散提示）、
  `layouts/AppLayout.vue`（顶部栏 + 桌面侧边栏 + 移动底部导航）、`stores/app.ts`。
- 目录：`storage/{uploads,exports,logs}`、`backups/`（只留 `.gitkeep`，内容不入库）。

### 变更

- `backend/alembic/` → **`backend/migrations/`**（按约定命名），`alembic.ini` 的 `script_location` 同步。
- API 端口从 8080 改为 **8000**（仅容器内）；对外统一走 web 容器的 8080。
- `/api/v1/*` 响应统一为 `{success, data, message, request_id}` 信封（此前 `/ping`、`/health` 返回裸对象，
  导致前端取 `data` 为空并误报"无法连接后端"）。
- 连接池状态字段由 `overflow`（会变负、语义歧义）改为 `max_overflow`（配置上限）。
- `.env.example` 补齐日志、连接池、端口等变量。

### 修复

- 前端 `vue-tsc` 两处类型错误：路由数组缺 `RouteRecordRaw[]` 标注；Vite 8 的 `manualChunks` 只接受函数形式。
- 容器内 `npm ci` 因 macOS 生成的 lockfile 缺少 linux-musl 可选依赖而失败 → 改用 `npm install`；
  同时容器内直连 registry.npmjs.org 出现 ECONNRESET → 默认改用 npmmirror（可用 `NPM_REGISTRY` 覆盖）。

### 数据库

- 无结构变更（仍为 25 表 / 2 视图 / `0001_init`）。验证：干净库 `alembic upgrade head` → 25 表 + `0001_init`。

---

## [Unreleased]

### 新增

- `AGENTS.md` §12「上下文管理与开发状态持久化」：开发前必读、功能完成后的记录义务、
  任务收尾八项清单、上下文压缩后的恢复流程、核心逻辑保护、规则与执行者对照、提交粒度与可回退。
- 自动化机制：`.githooks/{pre-commit,post-commit,pre-push}`、
  `scripts/{install-hooks,session-start,status-snapshot,db-init,migrate-safe,check-docs}.sh`、
  `.github/workflows/ci.yml`、`docs/state/`（状态留痕目录）。
- `scripts/db-init.sh`：建库 → DDL → 自动 `alembic stamp`，修掉"手动建库后版本表为空"的隐患。
- `scripts/migrate-safe.sh`：迁移前自动 `pg_dump`，失败时打印回滚命令。

### 变更

- 文档结构调整：`PRD.md` `ARCHITECTURE.md` `DEVELOPMENT_PLAN.md` `PROJECT_STATUS.md` `CHANGELOG.md`
  统一移入 `docs/`；旧版过程文档移入 `docs/archive/`（`architecture-v3-passkey.md`、
  `implementation-plan-v4-node.md`、`prd-alignment.md`）。
- 本机 PostgreSQL 16.15 安装完成并验证：25 表 / 2 视图 / 37 外键 / 2 条 trgm 索引；
  `EXPLAIN` 确认命中 `ix_ingredients_name_trgm`。
- pip 安装路径统一为「优先 uv、回退镜像」，Dockerfile 增加 `PIP_INDEX_URL` 构建参数。

### 修复

- 手动执行 `database/001_init.sql` 后 `alembic_version` 为空，会让后续 `alembic upgrade head`
  重复建表并报 `relation already exists`；已 `alembic stamp 0001_init` 补齐，并纳入 `db-init.sh`。

### 验证（2026-11-09）

- **Docker 可用**：Docker Desktop 4.98.0 / 引擎 29.9.2 / Compose 5.6.1；`docker run hello-world` 通过；
  本项目 `docker compose up -d --build` 37 秒构建成功，`freshkeep-api` 与 `freshkeep-db` 均 healthy。
  `/health` → `{"status":"ok","db":true}`；容器内 `alembic current` → `0001_init (head)`；
  25 张表；`database/002_acceptance_check.sql` 8 条断言全部通过。
- **Docker CLI 修复**：原 `docker` 不在 PATH（只在 `~/.docker/bin` 与 app 包内），已向 `~/.zshrc` 追加 PATH 行，
  新开 shell 验证 `which docker` 命中 `~/.docker/bin/docker`。
- **Xcode 可用**：27.2（27B52），`xcode-select -p` 指向外接盘 `/Volumes/移动硬盘/XcodeApps/Xcode.app/Contents/Developer`；
  `/Applications/Xcode.app` 为符号链接；`-checkFirstLaunchStatus` 退出码 0；iOS 27.2 SDK 齐备；
  `xcrun swiftc` 编译并运行成功。外接卷 APFS（`noowners`、无 `noexec`、无 quarantine）→ 无权限问题。
- **发现缺口**：iOS 模拟器运行时为 0（`simctl list runtimes` 空），根卷仅剩 16 GiB，暂不下载（约 7~9 GB），
  改为真机出包路线。
- 本地生成 `.env`（随机 `POSTGRES_PASSWORD`），`docker compose config` 校验通过；`.env` 已在 `.gitignore` 中。

### 数据库

- 无 DDL 变更；新增 `alembic_version` 表（值为 `0001_init`），仅记录版本，不改变业务结构。

---

## 2026-11-08 · 阶段 0：项目准备（`ef47d78`）

### 新增

- `database/001_init.sql`：25 张表 + 2 个视图 + 37 个外键 + `updated_at` 触发器。
- `database/002_acceptance_check.sql`：PRD 三条关键用例的数据库侧断言 + 四类约束反向验证。
- `backend/`：FastAPI 装配（`/health`、`/api/v1/ping`、`x-request-id`、统一错误）、配置、会话、Alembic 0001、CLI（`pair`/`devices`/`revoke`）、pytest 冒烟 4 条。
- `frontend/`：Vue 3 + TS + Vite + Pinia 骨架，5 个视图占位，统一 API 客户端（Web Cookie / App Bearer）。
- `docker-compose.yml`（api + db）、`backend/Dockerfile`、`.env.example`、`.dockerignore`。
- `deploy/`：NAS 部署手册、`backup.sh`、`restore.sh`。
- `PRD.md`、`docs/api.md`、`docs/database.md`、`docs/er-diagram.md`、`AGENTS.md`（PRD 后在文档重整中移到根目录）。

### 数据库

- **首次建立结构**：`users` `devices` `pair_codes` `file_assets` `categories` `units` `storage_locations`
  `ingredients` `ingredient_barcodes` `nutrition_definitions` `ingredient_nutrition` `nutrition_targets`
  `batches` `inventory_transactions` `transaction_allocations` `consumption_records` `consumption_nutrition`
  `shopping_lists` `shopping_list_items` `recipes` `recipe_items` `notifications` `app_settings` `audit_logs` `idempotency_keys`。
- 视图：`v_inventory`、`v_batch_reconcile`。
- 迁移：`alembic/versions/0001_init.py`（执行 `001_init.sql`，剥掉自带 `BEGIN/COMMIT`）。
- 验证：消耗 300g → 成本 `10.80`、剩余 `42.20`、营养 `495.0000 kcal`、对账差异 0；负库存/重复分配/正 delta/孤儿快照均被拒。

---

## 2026-11-08 · 最终开发方案定稿（`9f02d60`）

### 文档

- `docs/final-plan.md`：8 处冲突全部定案——认证改为「配对码 → 长期设备令牌」（Web Cookie / App Bearer，不做密码）；
  产品形态为原生 App + Web；放弃 PWA 改用 App 本地通知；数据库 PostgreSQL 16；后端 FastAPI + 同步 SQLAlchemy；
  前端 Vue 3；双计量独立余额；批次余额为缓存 + 每日对账。
- 明确对 PRD 的 4 处必要偏离（不做密码、不做 PWA、容器 5→2、Cookie 无 Secure）及原因。

### 数据库

- 无实际变更（设计层面确定 25 表方案）。

---

## 2026-11-08 · PRD 对齐分析（`c685cf1`）

### 文档

- `docs/prd-alignment.md`：识别出 PRD 与既有方案的 8 处冲突、4 处需定死的细节；量级对比（2 表 → 25 表）；
  P0 工期重估（15.5 → 32 人日）。
- 实测环境能力：pip 可用、npm 可用、无 Docker、无 PostgreSQL。

---

## 2026-11-08 · 方案 v3（Passkey，已被取代）（`d597df7`）

### 文档

- `docs/architecture.md`：仅 Passkey 方案（WebAuthn + Tailscale sidecar + 零依赖验签）。
  该版本**已被 v4 取代**，Passkey 章节仅作技术备查。

---

## 2026-11-08 · 方案 v2（内网 + 账号密码，已被取代）（`d2cf7d2`）

### 文档

- `docs/architecture.md`：去除公网暴露、账号密码 + 会话、`ALLOW_CIDR` 白名单、参考 grocy/mealie 的建模。

---

## 2026-11-08 · 首版纯前端应用（`4823511` `f78087a` `0865189`）

### 新增

- 纯前端单页应用（`index.html` + `css/style.css` + `js/store.js` + `js/app.js` + `sw.js` + manifest）：
  库存台账、一键扣减、临期提醒、消耗统计、JSON/CSV 导出。
- `tests/selftest.html`：48 条确定性用例（日期解析、扣减边界、撤销、统计口径、CSV 转义、坏数据兜底）。
- `docs/screenshots/`：5 张移动端截图（webp）。

### 数据库

- 无（数据存浏览器 localStorage）。

> 该版本现在是**设计参考**（交互与信息架构），不是交付形态。
