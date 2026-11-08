# 项目状态

> 快照时间：2026-11-09 02:45（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `docs/CHANGELOG.md`。

---

## 1. 一句话现状

**M4 消耗域已完成**（风险最高的里程碑）：FEFO 分配 + `FOR UPDATE` 行锁、成本分摊与尾差结清、
双计量、营养快照冻结、批量整批回滚、撤销反向流水，以及消耗录入页与记录页全部落地。
PRD §7.1 的 **9 条验收用例在 `tests/acceptance/` 全绿**，pytest **92 项通过**，
容器真实 HTTP **22 项断言全过**，浏览器真实点击提交消耗后结果区正确显示成本与批次分配。
本轮**无 DDL 变更**，两库迁移版本均为 `0002_ingredient_storage`。下一步是 **M5 库存域**。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 文档、规则、骨架、数据库评审 |
| 阶段 1 | ✅ 完成 | 三容器 + 前后端骨架 + 日志与异常 |
| 阶段 2 | ✅ 完成 | 认证 / 分类 / 单位 / 位置 / 食材 / 图片 / 搜索 / 条码 |
| M0 骨架收尾 | ✅ 完成 | CIDR + 幂等中间件 + CI |
| M1 认证 | ✅ | 已由阶段 2.1 交付 |
| M2 档案域 | ✅ | 已由阶段 2.2~2.8 交付 |
| M3 批次域 | ✅ 完成 | 五步事务 / 查询 / 状态机 / 前端批次区 |
| **M4 消耗域** | ✅ **完成** | 9 条验收全绿；证据见 §2.4 |
| M5 库存域 | ⬜ **下一步** | `v_inventory`、流水聚合、盘点、报损 |
| M6 首页与营养 | ⬜ | dashboard、营养目标、日汇总 |
| M7 备份导出 | ⬜ | |
| M8 前端页面 | 🔄 部分 | 登录/库存/详情(含批次)/编辑/设置/消耗/记录已完成；记录页完整流水待 M5 |
| M9 原生 App | ⬜ | 需 Xcode（iOS 走真机自签） |
| M10 联调验收 | ⬜ | |

整体进度：**P0 完成 7/13 个里程碑（约 54%）**；按人日约 18.5/36。

---

## 2. 已完成（可验证的证据）

### 2.1 阶段 2：基础资料管理

| 模块 | 验证方式与结果 |
| --- | --- |
| 2.1 认证 | 配对码换 Cookie；密码登录返回 Bearer；退出/吊销即时失效 |
| 2.2 分类 | 两级结构；同级重名 409；三级嵌套 400；有食材时删除 409；`/sort` 批量改序 |
| 2.3 单位 | 9 个内置单位；维度隔离；内置拒删 409 |
| 2.4 位置 | 冷冻室/冷藏室/常温/橱柜；被引用拒删 |
| 2.5 食材档案 | 详情页六项属性与分类标签用 DOM 探针 12 项全 true 核对 |
| 2.6 图片 | 魔数校验（非图片 415）、5MB 上限、sha256 去重、`/raw` 正确 MIME、被引用拒删 409 |
| 2.7 搜索 | `鸡`/`ji`/`jxr`/`JIXIONG` 四种输入均命中；无关词不误命中 |
| 2.8 条码 | 查询/绑定/解绑；重复 409；未绑定 404 |

### 2.2 M0 骨架收尾

| 项 | 验证方式与结果 |
| --- | --- |
| 网段白名单 | 7 组判定矩阵：回环/局域网/组网放行，`8.8.8.8`、`1.1.1.1` 拒绝 |
| 写操作幂等 | 同 key 同 body 返回原响应 + `Idempotency-Replayed: 1`；同 key 不同 body 409 |
| CI | `.github/workflows/ci.yml` 三个 job |

### 2.3 M3 批次域

| 项 | 验证方式与结果 |
| --- | --- |
| 入库五步事务 | `POST /batches` 同事务写批次 + `purchase` 流水 + 自分配；`v_batch_reconcile` 三个 diff 为 0 |
| 查询接口 | `GET /batches`（分页/筛选）、`/{id}`、`/expiring?days=7`、`/expired`；容器 E2E 18 项全过 |
| 状态机 / 元数据禁改 | 归零→depleted、恢复→active；`PUT` 带 `remaining_*`/`purchase_cost`/`status` 一律 400 |
| 前端 | 详情页 1280/390 DOM 探针：批次区、剩余 500g、临期标签、¥18.00 全 true |

### 2.4 M4 消耗域（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 验收层 | `tests/acceptance/test_consumption.py` | PRD §7.1 九条用例先写全红（9 failed），实现后 **9 passed**；从 `database/002` 平移到真实 HTTP + 真 PG 事务 |
| FEFO + 行锁 | `services/consumption/__init__.py` | 两线程同时扣 400g（总量 500g）→ `[201, 422]`、余额 100g；**反向验证**：去掉 `with_for_update` 测试立即变红，恢复后通过 |
| 成本与尾差 | 同上 | 500g/18元 + 1000g/35元，消耗 300g → 成本 **10.80**、B1 剩 200g·7.20、总成本 **42.20**；批次扣完时成本归 0 |
| 营养快照 | 同上 | 300g × 165kcal/100g = **495.0000**；改档案到 170 后历史仍 495、新消耗 340 |
| 库存不足 / 批量回滚 | 同上 | 2000g > 可用 500g → 422 且无部分流水；批量一项不足 → 整批 422、不产生部分消耗单 |
| 撤销 | `state.py` + `reverse()` | 新增 1 条 `reverse` 流水、余额恢复 1500g、原记录 `reversed` 保留、对账 diff 0 |
| 幂等 | 全局中间件 | 同 key 同 body 两次返回同一消耗单，第二次 `Idempotency-Replayed: 1` |
| 契约缺口补齐 | `PUT /ingredients/{id}/nutrition` | docs/api.md §3.2 声明但阶段 2 未实现；现按版本化整体替换，历史快照不受影响 |
| 前端 | `ConsumeView.vue`、`RecordsView.vue` | 1280/390 DOM 探针横向溢出 0px；真实点击提交 100g 后结果区显示 ¥3.60 与批次分配 |

### 2.5 测试规模

```
backend/tests/
  conftest.py                    182 行   真实 PG 测试库 + 每例清库
  unit/test_pinyin.py             50 行   拼音生成 + 搜索条件（11 项）
  unit/test_batch_state.py        78 行   批次状态迁移（9 项）
  api/test_system.py              59 行   健康/信封/请求 id/日志上报（6 项）
  api/test_stage2.py             335 行   阶段 2 全部接口（25 项）
  api/test_middleware.py         150 行   CIDR + 幂等（14 项）
  api/test_batches.py            346 行   批次域（18 项）
  acceptance/test_consumption.py  ~260 行  PRD §7.1 九条验收（9 项，M4 新增）
合计 92 项，全绿
```

---

## 3. 未完成（明确列出，避免误判）

| 项 | 现状 |
| --- | --- |
| 库存域（`v_inventory` 查询、盘点、报损、调整） | 未开始；**M5 是下一步**，`GET /inventory/transactions` 尚未实现 |
| 记录页完整流水 | 目前只展示消耗记录；入库/调整/报损流水待 M5 接口 |
| 首页与营养统计 | 首页仍是链路自检卡片，无业务数字 |
| 备份导出接口 | 未实现（脚本 `deploy/backup.sh` 可用，但无 API） |
| APScheduler 定时任务 | 依赖已装，未启用（临期扫描/每日对账） |
| Capacitor 原生工程 | 未 `cap add`，`android/` `ios/` 不存在 |
| NAS 部署验证 | 本机 compose 已通过；NAS 未跑过 |
| 消耗列表翻页 UI | 前端固定取最近 50 条，未做翻页（接口已支持分页） |

---

## 4. 已知问题

| # | 问题 | 影响 | 当前处置 | 状态 |
| --- | --- | --- | --- | --- |
| K11 | 两库迁移版本曾漂移 | 本机直连后端缺列 500 | `scripts/migrate-safe.sh` 已迁移，回滚点 `backups/pre-migrate-freshkeep-20261109-015103.dump` | ✅ 已修复 |
| K16 | M3 列表响应曾多套一层 `items` | 批次区不渲染数据 | 已与阶段 2 分页结构对齐，DOM 探针复验通过 | ✅ 已修复 |
| K17 | `FOR UPDATE` 与 `lazy="joined"` 的 OUTER JOIN 冲突 | 消耗接口 500 | 改用 `with_for_update(of=Batch)` 只锁主表；反向验证确认行锁有效 | ✅ 已修复 |
| K18 | `NutritionReplace` 定义在路由模块导致 OpenAPI 生成失败 | `/docs` 打不开 | 移到 `schemas/ingredient.py`，OpenAPI 42 条路径可生成 | ✅ 已修复 |
| K12 | `session-start.sh` 只检查本机 PG | 两库版本漂移不会自动发现 | 已知；§6 提供容器库核对命令 | ⚠️ 已知 |
| K9 | 无 iOS 模拟器运行时 | 不能跑 `npx cap run ios` | 根卷仅剩 16 GiB，走真机自签路线 | ⚠️ 已知 |
| K13 | 幂等中间件缓冲请求体 | 大文件上传多占一份内存 | 单用户低频可接受 | ⚠️ 已知 |
| K14 | 幂等中间件对 multipart 按字节哈希 | 边界串不同判为不同请求 | 上传接口不带 `Idempotency-Key` | ⚠️ 已知 |
| K15 | 批次编号「当日计数 + 唯一约束」，无并发重试 | 并发同日入库极小概率冲突 | 单用户低频可接受 | ⚠️ 已知 |
| K19 | 营养基准单位只接受 g/kg | 体积/「份」基准返回 `NUTRITION_BASIS_MISMATCH` | PRD §8 明确不做密度换算，属既定决策 | ℹ️ 既定限制 |

已关闭：K1~K8、K10。

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | `backend/.venv`，pytest 92 项可用 |
| 本机 PostgreSQL | ✅ 16.15 | 库 `freshkeep` 与测试库 `freshkeep_test`，均在 `0002` |
| 容器三件套 | ✅ | `freshkeep-{db,api,web}` 全 healthy，对外 8080 |
| 容器内迁移版本 | ✅ | `0002_ingredient_storage` |
| 前端构建 | ✅ | `npm run build` 通过（vue-tsc 零错误） |
| Docker / Xcode / Node | ✅ | 4.98.0 / 27.2（外接盘）/ 22.22 |

---

## 6. 上下文清空后如何恢复

```bash
./scripts/session-start.sh                 # 一条命令看全貌
cat AGENTS.md docs/PRD.md docs/ARCHITECTURE.md
cat docs/DEVELOPMENT_PLAN.md docs/PROJECT_STATUS.md
head -120 docs/CHANGELOG.md
```

**三处状态必须交叉核对**：

```bash
git status --short && git log -3 --oneline
cd backend && .venv/bin/python -m pytest          # 期望 92 passed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps                                  # 期望 3 个 healthy
docker compose exec -T db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
psql -d freshkeep -tAc "select version_num from alembic_version"   # 两库应一致
```

---

## 7. 下一步（M5 库存域）

按 `docs/DEVELOPMENT_PLAN.md` 的 M5，顺序如下：

1. `GET /inventory`、`/inventory/summary`、`/inventory/transactions`（读 `v_inventory` 与流水聚合）；
2. 盘点调整：`POST /inventory/adjustments` 提交**实际值**、服务端反算 delta，写 `adjustment` 流水；
3. 报损：`POST /inventory/spoilage`（`spoilage` 流水，负 delta，同样走五步）；
4. 批量盘点整批事务；撤销后的统计口径要排除 `status='reversed'` 的消耗单；
5. 把盘点/报损的用例补进 `tests/acceptance/`，继续保证 `v_batch_reconcile` 差异为 0；
6. 记录页接入完整流水，首页接业务数字（可与 M6 协同）。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-09 02:45 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `cf6c591` |
| 工作区 | 1 个未提交改动，未跟踪 0 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0002_ingredient_storage`，25 张表 |
| 后端测试 | 92 passed, 1 warning in 5.83s |
| 前端产物 | 已构建 |
| 文档检查 | 通过 |

最近 5 次提交：

```
cf6c591 2026-11-09 feat(api): M4 消耗域 —— FEFO/成本分摊/尾差/营养快照/撤销 + 验收层
ba3a3a6 2026-11-09 chore: 刷新 M3 提交后的状态快照与留痕
2b722f0 2026-11-09 feat(api): M3 批次域 —— 入库五步事务、查询、状态机与前端批次区
1e575c0 2026-11-09 chore: 补齐状态留痕（commits.log）
0c37dca 2026-11-09 docs(db): 同步 ingredients.default_storage_location_id 与迁移历史
```
<!-- AUTO:STATUS:END -->
