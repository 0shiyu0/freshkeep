# 项目状态

> 快照时间：2026-11-08 23:30（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `CHANGELOG.md`。

---

## 1. 一句话现状

**阶段 0（项目准备）已完成并推送，开发环境已就绪**（PostgreSQL 16.15 已在本机运行并通过全部验收用例）。
代码尚未开始。数据库结构（25 表 / 2 视图 / 37 外键 / 2 条 trgm 索引）已在真库执行并断言通过，
Alembic 基线已对齐到 `0001_init`。下一个里程碑是 **M0 骨架收尾**。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 6 项交付物齐备，见 §2 |
| M0 骨架收尾 | 🔄 进行中 | 0.1/0.2/0.4 已在本地 Docker 上验证；0.3/0.5/0.6/0.7 未做 |
| M1 认证 | ⬜ | |
| M2 档案域 | ⬜ | |
| M3 批次域 | ⬜ | |
| M4 消耗域 | ⬜ | 风险最高，先写失败测试 |
| M5 库存域 | ⬜ | |
| M6 首页与营养 | ⬜ | |
| M7 备份导出 | ⬜ | |
| M8 前端 5 页 | ⬜ | |
| M9 原生 App | ⬜ | 需 Xcode（iOS）|
| M10 联调验收 | ⬜ | |

整体进度：**P0 完成 1/11 个里程碑（约 9%）**；按人日计约 2/36。

---

## 2. 已完成（阶段 0 明细）

| 交付物 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 项目规则 | `AGENTS.md` | 11 节，含 Decimal 铁律、库存写入五步、FEFO 加锁、提交规范、禁止事项 |
| 产品需求 | `PRD.md` | 范围/规则/9 条验收/原待明确项全部拍板 |
| 系统架构 | `ARCHITECTURE.md` | 拓扑、分层、请求管线、认证、数据模型、API 总表、四算法、ADR |
| 数据库设计 | `database/001_init.sql` + `docs/database.md` + `docs/er-diagram.md` | 25 表 / 2 视图 / 37 外键；实跑建库成功 |
| 数据库自检 | `database/002_acceptance_check.sql` | 消耗成本 `10.80`、剩余 `42.20`、营养 `495`、对账差异 `0`、四类错误被约束拒绝 |
| 后端骨架 | `backend/app/*` | `uvicorn` 起服务：`/health`、`/api/v1/ping`、`x-request-id`、`/api/v1/nope`→404；`pytest` 4 passed |
| 前端骨架 | `frontend/*` | 目录与路由齐备；**依赖未安装、未构建**（见已知问题 K4） |
| 部署文件 | `docker-compose.yml`、`backend/Dockerfile`、`deploy/*` | **未在 Docker 上验证**（本机无 Docker，见 K1） |
| 开发计划 | `DEVELOPMENT_PLAN.md` | 阶段 0 + M0~M10 + P1/P2 |
| 变更记录 | `CHANGELOG.md` | 从首版到现在的全部变更，含数据库小节 |

---

## 3. 未完成（明确列出，避免以为已完成）

| 项 | 现状 |
| --- | --- |
| 数据库层 25 表的 ORM 模型 | 只有 DDL，`backend/app/models/` 为空 |
| Pydantic schema | `backend/app/schemas/` 为空 |
| 业务 service（FEFO/成本/营养/对账） | 未写，仅在设计文档中给出伪代码 |
| api/v1 路由 | 仅 `/ping`；其余未实现 |
| 中间件（CIDR / 认证 / 限流 / 幂等） | 仅 request_id 与 CORS |
| 前端 5 个页面 | 占位组件，无逻辑 |
| Capacitor 原生工程 | 未 `cap add`，`android/` `ios/` 目录不存在 |
| CI | 无 workflow |
| 部署验证 | 未在 NAS 上跑过 |

---

## 4. 已知问题（按影响排序）

| # | 问题 | 影响 | 当前处置 | 状态 |
| --- | --- | --- | --- | --- |
| K1 | ~~本机无 Docker~~ | — | **已解决**：Docker Desktop 4.98.0（引擎 29.9.2 / Compose v5.6.1）可用；`docker compose up -d --build` 37 秒构建成功，两容器 healthy，`/health` 返回 `db:true`，容器内 Alembic `0001_init (head)`、25 表、8 条验收断言通过 | ✅ 已关闭 |
| K2 | ~~本机 PostgreSQL 无法由 agent 进程安装~~ | — | **已解决**：用户在终端执行 `brew install postgresql@16` 成功，服务已启动（`pg_isready` → accepting connections），库 `freshkeep` 建好并在真库上跑通验收脚本 | ✅ 已关闭 |
| K3 | ~~`pg_trgm` 未在真 PG 验证~~ | — | **已解决**：真库中 `trgm_idx=2`；`EXPLAIN` 在 `enable_seqscan=off` 下命中 `Bitmap Index Scan on ix_ingredients_name_trgm`；中文/拼音/首字母检索均返回正确结果 | ✅ 已关闭 |
| K4 | 前端依赖未安装 | `frontend/dist` 不存在，后端静态托管不生效，网页会 404 | `cd frontend && npm ci && npm run build`（镜像与命令见 environment.md） | ⚠️ 已知 |
| K5 | ~~无 Xcode~~ | — | **已解决**：Xcode 27.2 装在外接盘且可用（`xcodebuild -version`、`xcrun swiftc` 编译运行均通过）。**注意**：外接盘未挂载时整套工具链失效 | ✅ 已关闭 |
| K9 | 无 iOS 模拟器运行时 | 不能跑 `npx cap run ios` 模拟器调试 | 根卷只剩 16 GiB，iOS runtime 约 7~9 GB。建议用真机调试（`xcodebuild` + 自签），需要模拟器时先腾空间再 `xcodebuild -downloadPlatform iOS` | ⚠️ 已知 |
| K6 | 旧文档与最终方案不一致 | `docs/architecture.md`（Passkey）、`docs/implementation-plan.md`（Node/SQLite）、`docs/prd-alignment.md`（双通道认证）已是历史版本 | 三个文件头部均已标注"被取代"，以 `ARCHITECTURE.md` 与 `PRD.md` 为准 | ✅ 已标注 |
| K7 | ~~无 CI~~ | — | **已解决**：`.github/workflows/ci.yml` 三个 job（后端含真 PG 迁移与验收、前端构建、文档检查） | ✅ 已关闭 |
| K8 | 手动 `psql -f` 建库后 `alembic_version` 为空 | 之后 `alembic upgrade head` 会重复建表并报 `relation already exists` | 已 `alembic stamp 0001_init` 补齐基线；`scripts/db-init.sh` 把这个步骤自动化 | ✅ 已修复（新增脚本防复发） |

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | 依赖已装（`backend/.venv`），`pytest` 可用 |
| pip | ✅ 可用（已加速） | 默认源 6 分 33 秒 → 镜像 + `--only-binary` 24.7 秒 → uv 1.3 秒；`scripts/dev-setup.sh` 已内置优先 uv |
| npm | ✅ 可用 | `npm view` 正常，镜像可选 |
| PostgreSQL 本地 | ✅ 16.15 运行中 | 库 `freshkeep`，25 表 / 2 视图 / 37 外键 / 2 trgm 索引，Alembic `0001_init (head)` |
| PGlite（PG16 WASM） | ✅ | 用于无 PG 环境下验证 DDL 与 SQL 语义 |
| Docker | ✅ 4.98.0（引擎 29.9.2） | CLI 原不在 PATH，已写入 `~/.zshrc`；`docker compose up` 已实测通过 |
| Xcode | ✅ 27.2（27B52） | 装在外接盘 `/Volumes/移动硬盘/XcodeApps/Xcode.app`，`/Applications/Xcode.app` 为符号链接；swiftc 编译实测通过；**无 iOS 模拟器运行时** |
| Node 22.22 | ✅ | 满足 Vite 8 / Capacitor 8 要求 |

---

## 6. 上下文清空后如何恢复（按此顺序读）

```bash
# 1. 我该遵守什么规则
cat AGENTS.md

# 2. 产品要做什么、不做什么、验收数字
cat PRD.md

# 3. 系统怎么搭：分层、认证、数据模型、API
cat ARCHITECTURE.md

# 4. 现在做到哪、下一步做什么
cat DEVELOPMENT_PLAN.md PROJECT_STATUS.md

# 5. 最近改了什么、数据库动过什么
head -60 CHANGELOG.md

# 6. 需要字段级/接口级细节时再往下翻
ls docs/            # database.md / er-diagram.md / api.md / final-plan.md
```

**一分钟自检命令**（确认环境还能跑）：

```bash
cd backend && .venv/bin/python -m pytest           # 期望 4 passed
cd ../frontend && npm run build                     # 期望生成 dist/
psql -d freshkeep -c "\dt" | wc -l                  # 期望 25+ 行
```

---

## 7. 下一步（M0 的具体动作）

本机已具备条件（PG 就绪、依赖已装），以下可立即开工：

1. 补 `ALLOW_CIDR` 中间件与幂等中间件，用 `curl` 覆盖「非白名单 403」与「重复 `Idempotency-Key`」两条分支；
2. 让后端连上本地库（`DATABASE_URL=postgresql+psycopg://shiyu@127.0.0.1:5432/freshkeep`），
   把 `/health` 的 `db` 从 `false` 变 `true`；
3. `cd frontend && npm ci && npm run build`，确认 `/` 返回 SPA 且 `/api/v1/*` 不被静态托管兜住；
4. 建立 `backend/tests/acceptance/`，把 `database/002` 的 8 条断言平移成 pytest；
5. 在 NAS 上首次 `docker compose up -d --build`（唯一还缺的验证环节，本机无 Docker）。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-09 00:50 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `e8f0596` |
| 工作区 | 4 个未提交改动，未跟踪 0 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0001_init`，25 张表 |
| 后端测试 | 4 passed, 1 warning in 0.81s |
| 前端产物 | 不存在 |
| 文档检查 | 通过 |

最近 5 次提交：

```
e8f0596 2026-11-08 fix(scripts): 变量紧邻中文导致 unbound variable；表数排除 alembic_version
dacc7a6 2026-11-08 chore: 状态留痕文件入库 + 钩子逐项输出
217e753 2026-11-08 chore: 建立上下文管理与状态持久化机制
71e9518 2026-11-08 docs: 重整为 6 个根级文件的自足文档体系 + 环境手册与脚本
ef47d78 2026-11-08 chore: 阶段 0 —— 项目准备（文档、规则、骨架、数据库评审）
```
<!-- AUTO:STATUS:END -->
