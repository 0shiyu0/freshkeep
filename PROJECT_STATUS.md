# 项目状态

> 快照时间：2026-11-08 22:40（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `CHANGELOG.md`。

---

## 1. 一句话现状

**阶段 0（项目准备）已完成并推送**，代码尚未开始。数据库结构（25 表 / 2 视图 / 37 外键）已在真 PostgreSQL 16 内核上执行并断言通过，
后端骨架可启动、pytest 4 条通过。下一个里程碑是 **M0 骨架收尾**。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 6 项交付物齐备，见 §2 |
| M0 骨架收尾 | ⬜ 未开始 | 需 NAS 上的 Docker + PostgreSQL |
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
| K1 | 本机无 Docker | 无法本地验证 `docker compose`、镜像构建、迁移自动执行 | 交付时附 NAS 上逐步验证清单；M0 在 NAS 上首次验证 | ⚠️ 已知 |
| K2 | 本机 PostgreSQL 无法由 agent 进程安装 | 无法跑 `psql` 端到端；只能用 PGlite 验证内核语义 | 已确认：即使关闭工具沙箱，`brew` 解包仍被系统级 `sandbox-exec` 拒绝（7 分 45 秒后以 exit 71 失败）。**需在用户自己的终端执行**，步骤与验证见 `docs/environment.md` §2 路径 A；过渡期用 `scripts/verify-db.mjs`（PGlite） | ⚠️ 待用户执行 |
| K3 | `pg_trgm` 未在真 PG 验证 | 两条 GIN 索引（中文模糊、拼音）未验证 | PGlite 不带该扩展，验证时临时剔除；M0 用 `postgres:16-alpine` 补验 | ⚠️ 已知 |
| K4 | 前端依赖未安装 | `frontend/dist` 不存在，后端静态托管不生效，网页会 404 | `cd frontend && npm ci && npm run build`（镜像与命令见 environment.md） | ⚠️ 已知 |
| K5 | 无 Xcode | 不能本地出 IPA | 用户提供 Xcode 16+ 后本地 `xcodebuild`；备用 GitHub Actions macOS runner | ⚠️ 已知 |
| K6 | 旧文档与最终方案不一致 | `docs/architecture.md`（Passkey）、`docs/implementation-plan.md`（Node/SQLite）、`docs/prd-alignment.md`（双通道认证）已是历史版本 | 三个文件头部均已标注"被取代"，以 `ARCHITECTURE.md` 与 `PRD.md` 为准 | ✅ 已标注 |
| K7 | 无 CI | 回归靠手工 | M0 加 GitHub Actions：`pytest` + `npm run build` | ⬜ 待办 |

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | 依赖已装（`backend/.venv`），`pytest` 可用 |
| pip | ✅ 可用（已加速） | 默认源 6 分 33 秒 → 镜像 + `--only-binary` 24.7 秒 → uv 1.3 秒；`scripts/dev-setup.sh` 已内置优先 uv |
| npm | ✅ 可用 | `npm view` 正常，镜像可选 |
| PostgreSQL 本地 | ❌ 装不上（系统级限制） | agent 进程无法运行 `brew` 的 sandbox 解包；用户终端可装，或用 PGlite 替代 |
| PGlite（PG16 WASM） | ✅ | 用于无 PG 环境下验证 DDL 与 SQL 语义 |
| Docker | ❌ 未安装 | 影响 compose 验证 |
| Xcode | ❌ 未安装 | 影响 iOS 出包 |
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

1. 在 NAS 上首次 `docker compose up -d --build`，确认 `/health` 返回 `db:true`；
2. `alembic current` 应为 `0001_init (head)`，且 25 表存在；
3. 补 `ALLOW_CIDR` 与幂等中间件，并用 `curl` 覆盖 403 与重复请求两条分支；
4. `cd frontend && npm ci && npm run build`，确认 `/` 返回 SPA 且 `/api/v1/*` 不被兜住；
5. 在真 PG 上补验 `pg_trgm` 两条索引用例；
6. 加最小 CI（pytest + build）。
