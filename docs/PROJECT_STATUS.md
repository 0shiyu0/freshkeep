# 项目状态

> 快照时间：2026-11-09 02:05（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `docs/CHANGELOG.md`。

---

## 1. 一句话现状

**阶段 2（基础资料管理）已完成**：认证、分类、单位、储存位置、食材档案、图片、搜索、条码八项全部可用；
后端 56 项测试全绿、容器上 61 项端到端断言全过、五个页面在桌面与移动两种宽度下布局无溢出。
M0 收尾也已补齐（网段白名单 + 写操作幂等 + CI）。下一步是 **M3 批次域**。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 文档、规则、骨架、数据库评审 |
| 阶段 1 | ✅ 完成 | 三容器 + 前后端骨架 + 日志与异常 |
| 阶段 2 | ✅ 完成 | 认证 / 分类 / 单位 / 位置 / 食材 / 图片 / 搜索 / 条码 |
| M0 骨架收尾 | ✅ 完成 | CIDR + 幂等中间件 + CI 全就位 |
| M1 认证 | ✅ | 已由阶段 2.1 交付 |
| M2 档案域 | ✅ | 已由阶段 2.2~2.8 交付 |
| M3 批次域 | ⬜ **下一步** | 入库建批次、批次查询、状态流转 |
| M4 消耗域 | ⬜ | 风险最高，先写失败测试 |
| M5 库存域 | ⬜ | |
| M6 首页与营养 | ⬜ | |
| M7 备份导出 | ⬜ | |
| M8 前端页面 | 🔄 部分 | 登录/库存/详情/编辑/设置已完成；记录页仍是占位 |
| M9 原生 App | ⬜ | 需 Xcode（iOS）|
| M10 联调验收 | ⬜ | |

整体进度：**P0 完成 5/13 个里程碑（约 38%）**；按人日计约 9.5/36。

---

## 2. 已完成（可验证的证据）

### 2.1 阶段 2：基础资料管理

| 模块 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 2.1 认证 | `api/v1/auth.py`、`services/auth.py`、`api/deps.py`、`views/LoginView.vue`、`stores/auth.ts` | 配对码换 Cookie；密码登录返回 Bearer；退出/吊销即时失效；`has_password` 如实反映状态。pytest 4 项 + 浏览器内真实走完配对登录（落在 `/`、页面内能取到 1 个食材） |
| 2.2 分类 | `api/v1/categories.py` | 两级结构；同级重名 409；三级嵌套 400；有食材时删除 409；`/sort` 可批量改序 |
| 2.3 单位 | `api/v1/units.py` | 9 个内置单位（g/kg/毫升/升/个/包/瓶/盒/袋）；维度隔离（数量单位不能填进重量位）；内置单位拒删 409 |
| 2.4 位置 | `api/v1/units.py`（loc_router） | 冷冻室/冷藏室/常温/橱柜；被引用拒删 |
| 2.5 食材档案 | `api/v1/ingredients.py`、`views/{Inventory,IngredientDetail,IngredientForm}View.vue` | 详情页逐项核对：名称、`肉类 · 常见食材`、`启用中`、`默认数量单位=包`、`默认重量单位=g`、`每包重量=250g`、`最低库存=500g`、`营养基准=每100g`、`储存位置=冷冻室`（DOM 探针 12 项全 true） |
| 2.6 图片 | `services/files.py`、`api/v1/files.py` | 魔数校验（非图片 415）；5MB 上限；sha256 去重（同图两次上传返回同一 id）；`/raw` 返回正确 MIME；被引用拒删 409 |
| 2.7 搜索 | `services/search.py` | `鸡`/`ji`/`jxr`/`JIXIONG` 四种输入均命中；无关词不误命中；完全匹配排首位；父分类筛选含子分类 |
| 2.8 条码 | `api/v1/barcodes.py` | 查询/绑定/解绑；一条码只属一个食材（重复 409）；未绑定 404 |

### 2.2 M0 骨架收尾（本轮补齐）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 网段白名单 | `core/middleware.py`（`CidrMiddleware`） | 7 组判定矩阵：回环/局域网/组网放行，`8.8.8.8`、`1.1.1.1` 拒绝；真实 ASGI 调用返回 403 且是统一信封 |
| 写操作幂等 | `core/middleware.py`（`IdempotencyMiddleware`） | 同 key 同 body → 第二次返回原 id 且带 `Idempotency-Replayed: 1`；同 key 不同 body → 409 `DUPLICATE_REQUEST`；失败响应不缓存；GET 不受影响。容器上用 curl 实测三态全部通过，库中只留 1 条记录 |
| CI | `.github/workflows/ci.yml` | 三个 job：后端（真 PG 迁移 + 验收断言 + pytest）、前端构建、文档检查 |

### 2.3 测试规模

```
backend/tests/
  conftest.py            182 行   真实 PG 测试库 + 每例清库
  unit/test_pinyin.py     50 行  拼音生成 + 搜索条件（11 项）
  api/test_system.py      59 行  健康/信封/请求 id/日志上报（6 项）
  api/test_stage2.py     335 行  认证/字典/食材/换算/图片/搜索/条码（25 项）
  api/test_middleware.py 150 行  CIDR + 幂等（14 项）
合计 56 项，全绿
```

---

## 3. 未完成（明确列出，避免误判）

| 项 | 现状 |
| --- | --- |
| 批次域（入库/批次/状态机） | 未开始。`batches` 表已建但无接口 |
| 消耗域（FEFO/成本/营养快照） | 未开始，仅设计文档有伪代码 |
| 库存域（`v_inventory` 查询、盘点、报损） | 未开始 |
| 首页与营养 | 首页仍是链路自检卡片，无业务数字 |
| 记录页 | `RecordsView.vue` 仍是 14 行占位（依赖流水，属 M5） |
| 配对页 | `PairView.vue` 已被 `/login` 取代，文件仍存在（可删） |
| 备份导出接口 | 未实现（脚本 `deploy/backup.sh` 可用，但无 API） |
| APScheduler 定时任务 | 依赖已装，未启用（临期扫描/对账） |
| Capacitor 原生工程 | 未 `cap add`，`android/` `ios/` 不存在 |
| NAS 部署验证 | 本机 compose 已通过；NAS 未跑过 |

---

## 4. 已知问题

| # | 问题 | 影响 | 当前处置 | 状态 |
| --- | --- | --- | --- | --- |
| K11 | 本机库与容器库曾出现迁移版本不一致（本机 `0001`、容器 `0002`） | 在本机直连后端时缺 `default_storage_location_id` 列会 500 | 已用 `scripts/migrate-safe.sh` 迁移本机库并留回滚点 `backups/pre-migrate-freshkeep-20261109-015103.dump`；两库现均为 `0002_ingredient_storage` | ✅ 已修复 |
| K12 | `session-start.sh` 只检查本机 PG，不检查容器库 | 两库版本漂移不会被自动发现 | 已知；§6 的自检命令里补了容器库版本核对 | ⚠️ 已知 |
| K9 | 无 iOS 模拟器运行时 | 不能跑 `npx cap run ios` | 根卷仅剩 16 GiB（iOS runtime 约 7~9 GB），走真机自签路线 | ⚠️ 已知 |
| K13 | `IdempotencyMiddleware` 会缓冲请求体 | 大文件上传（图片 ≤5MB）会多占一份内存 | 可接受：上传是单用户低频操作；若将来支持大文件需改为按路径跳过 | ⚠️ 已知 |
| K14 | 幂等中间件对 `multipart/form-data` 同样按字节哈希 | 同样的表单若边界串不同会被判为不同请求 | 上传接口不应带 `Idempotency-Key`；已在代码注释标注 | ⚠️ 已知 |

已关闭：K1（无 Docker）、K2（PG 装不上）、K3（trgm 未验）、K4（前端未构建）、K5（无 Xcode）、
K6（旧文档冲突）、K7（无 CI）、K8（alembic 基线）、K10（容器内 npm ECONNRESET）。

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | `backend/.venv`，pytest 56 项可用 |
| 本机 PostgreSQL | ✅ 16.15 | 库 `freshkeep` 与测试库 `freshkeep_test`，均在 `0002` |
| 容器三件套 | ✅ | `freshkeep-{db,api,web}` 全 healthy，对外 8080 |
| 容器内迁移版本 | ✅ | `0002_ingredient_storage` |
| 前端构建 | ✅ | `npm run build` 通过（vue-tsc 零错误） |
| Docker | ✅ 4.98.0 | CLI 路径已入库 `~/.zshrc` |
| Xcode | ✅ 27.2 | 外接盘；无模拟器运行时 |
| Node | ✅ 22.22 | 满足 Vite 8 / Capacitor 8 |

---

## 6. 上下文清空后如何恢复

```bash
# 0. 一条命令看全貌（推荐先跑这个）
./scripts/session-start.sh

# 1. 我该遵守什么规则
cat AGENTS.md

# 2. 产品要做什么、不做什么、验收数字
cat docs/PRD.md

# 3. 系统怎么搭
cat docs/ARCHITECTURE.md

# 4. 做到哪、下一步
cat docs/DEVELOPMENT_PLAN.md docs/PROJECT_STATUS.md

# 5. 最近改了什么、数据库动过什么
head -80 docs/CHANGELOG.md
```

**三处状态必须交叉核对**（只看一处会误判）：

```bash
git status --short && git log -3 --oneline        # 代码与提交
cd backend && .venv/bin/python -m pytest          # 期望 56 passed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps                                  # 期望 3 个 healthy
docker compose exec -T db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
psql -d freshkeep -tAc "select version_num from alembic_version"   # 两库应一致
```

---

## 7. 下一步（M3 批次域）

按 `docs/DEVELOPMENT_PLAN.md` 的 M3，顺序如下：

1. `models` + `schemas`：批次入库请求（数量/重量/成本/到期日/位置），复用阶段 2 的双计量校验；
2. `POST /batches`：**同一事务**写 `purchase` 流水 + `transaction_allocations` + 批次缓存（AGENTS.md §4.2 五步）；
3. `GET /batches`、`GET /batches/{id}`、`GET /batches/expiring`；
4. 状态机 `active → depleted`，只允许改元数据、不允许直接改数量（要改走盘点）；
5. 用 `v_batch_reconcile` 断言「流水分配聚合 == 批次缓存」，差异必须为 0；
6. 前端批次列表与入库表单。

**开工前必须先写失败测试**（M4 会用同一套断言）：入库后 `Σ allocation == batch.remaining_*`。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-09 01:53 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `1a1e3be` |
| 工作区 | 41 个未提交改动，未跟踪 34 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0002_ingredient_storage`，25 张表 |
| 后端测试 | 56 passed, 1 warning in 6.82s |
| 前端产物 | 已构建 |
| 文档检查 | 通过 |

最近 5 次提交：

```
1a1e3be 2026-11-09 feat(init): 阶段 1 项目初始化 —— 三容器 + 前后端骨架 + 日志与错误处理
0d5d3ff 2026-11-09 docs: Docker 与 Xcode 环境验证结论
e8f0596 2026-11-08 fix(scripts): 变量紧邻中文导致 unbound variable；表数排除 alembic_version
dacc7a6 2026-11-08 chore: 状态留痕文件入库 + 钩子逐项输出
217e753 2026-11-08 chore: 建立上下文管理与状态持久化机制
```
<!-- AUTO:STATUS:END -->
