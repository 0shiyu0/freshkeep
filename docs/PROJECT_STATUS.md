# 项目状态

> 快照时间：2026-11-11 10:40（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `docs/CHANGELOG.md`。

---

## 1. 一句话现状

**阶段 5 库存管理界面已完成**：库存总览改用 `/inventory` 聚合（与后端一致），
支持搜索 + 分类 + **状态（正常/临期/过期/无库存）** + 位置四条件组合筛选；
行内快速消耗、多选批量消耗、独立的盘点/报损页、详情页历史流水与单位成本、记录页日期与翻页。
pytest **158 项通过**（含状态筛选 7 项），浏览器实测移动端 390 快速消耗 500→400g、
批量消耗 440/450g 且 2 张消耗单、状态筛选只留 1 个食材。
本轮**无 DDL 变更**，两库均为 `0002_ingredient_storage`。下一步是 **M7 备份导出与定时任务**。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 文档、规则、骨架、数据库评审 |
| 阶段 1 | ✅ 完成 | 三容器 + 前后端骨架 + 日志与异常 |
| 阶段 2 | ✅ 完成 | 认证 / 分类 / 单位 / 位置 / 食材 / 图片 / 搜索 / 条码 |
| M0 骨架收尾 | ✅ 完成 | CIDR + 幂等中间件 + CI |
| M1 认证 | ✅ | 已由阶段 2.1 交付 |
| M2 档案域 | ✅ | 已由阶段 2.2~2.8 交付 |
| M3 批次域 | ✅ 完成 | 五步事务 / 查询 / 状态机 / 前端批次区 |
| M4 消耗域 | ✅ 完成 | 9 条验收全绿；证据见 §2.4 |
| **M5 库存域** | ✅ **完成** | 聚合/汇总/流水/盘点/报损；证据见 §2.5 |
| **阶段 3 采购入库** | ✅ **完成** | 独立入库页/批次列表/批次详情；证据见 §2.6 |
| **阶段 4 库存引擎** | ✅ **完成** | 独立引擎层 + 8 项必须测试 + 成本报告；证据见 §2.7 |
| **M6 首页与营养** | ✅ **完成** | summary / nutrition / targets + 首页改版；证据见 §2.8 |
| **阶段 5 库存界面** | ✅ **完成** | 库存总览/状态筛选/快消/批量/盘点报损/记录；证据见 §2.9 |
| M7 备份导出与定时任务 | ⬜ **下一步** | pg_dump、CSV/JSON 导出、APScheduler 对账 |
| M8 前端页面 | 🔄 部分 | 登录/库存/详情(含批次)/编辑/设置/消耗/记录已完成；记录页完整流水待 M5 |
| M9 原生 App | ⬜ | 需 Xcode（iOS 走真机自签） |
| M10 联调验收 | ⬜ | |

整体进度：**P0 完成 9/13 个里程碑（约 69%），另加阶段 3/4/5 的补齐**；按人日约 26/36。

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

### 2.5 M5 库存域（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 库存聚合 | `api/v1/inventory.py`、`schemas/inventory.py` | `GET /inventory` 读 `v_inventory`；搜索/分类（含子分类）/位置/低库存筛选；容器实测聚合 1500g / ¥53.00、批次数 2 |
| 汇总 | 同上 | `GET /inventory/summary`：总重量、总成本、食材数、批次数、低库存、临期 7 天、已过期 |
| 流水 | 同上 | `GET /inventory/transactions` 类型/食材/日期过滤；含 `related_object_id` 供记录页撤销 |
| 盘点 | `services/inventory/ops.py` | 提交实际值反算 delta；盘亏 -20g/-0.72、盘盈 +20g/+0.72 且 initial 同步上调；归零时成本结清、状态 depleted |
| 批量盘点 | 同上 | 任一项非法整批回滚（4800 与 -1 混测），余额不变 |
| 报损 | 同上 | FEFO 扣批次：b1(480g) 清零 + b2(1020g) 扣 120 → 剩 900g；缺原因 400 |
| 对账 | `v_batch_reconcile` | 盘点/盘盈/报损后差异始终为 0 |
| 前端 | `api/inventory.ts`、`RecordsView`、`InventoryView`、`IngredientDetailView` | 记录页全部流水 + 类型筛选 + 消耗撤销；库存页汇总条；详情页盘点/报损弹层；1280/390 溢出 0px |

### 2.6 阶段 3：采购入库与批次管理（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 3.1 入库页面 | `views/PurchaseView.vue`（`/purchase`） | 食材搜索选择、数量/重量/价格、单位成本预览、四个日期、位置、备注；浏览器真实填表提交 500g/18 元后显示批次号、`TX-P-` 流水号、`0.0360` |
| 3.2 独立批次 | `services/inventory/__init__.py` | 两次采购生成 `20261110-01` / `20261110-02`，id 与批次号都不同 |
| 3.3 四日期 | `schemas/batch.py` 增 `opened_date` | 购买/生产/到期/开封全部保存；两批次到期日各自独立 |
| 3.4 储存位置 | 入库表单 + `BatchCreate` | 位置「冷冻室」正确落库并在详情展示 |
| 3.5 成本 | `unit_cost` 快照 | 500g/18 元 → 0.0360；1000g/40 元 → 0.0400，互不影响 |
| 3.6 purchase 流水 | 五步事务 | 两条入库流水合计 1500g；库存总量 == 流水增量之和 |
| 3.7 批次列表 | `views/BatchesView.vue`、`GET /batches?q=` | 跨食材列表；`q=S3-E2E` 命中 2 个批次；状态/位置筛选可用 |
| 3.8 批次详情 | `views/BatchDetailView.vue`、`batch_id` 过滤 | 初始/剩余/采购/剩余/单位成本、四日期、位置、该批次流水；跨批次报损后两批次各自可见同一条流水 |

**验收 6 条**：两批次独立 ✅ / 价格独立 ✅ / 到期独立 ✅ / 自动流水 ✅ /
幂等不重复入库（同 key 只 1 个批次）✅ / 无来源库存增加（库存 == 流水、对账差异 0）✅。

### 2.7 阶段 4：库存引擎（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 独立引擎层 | `services/inventory/engine.py` | 纯函数，无 IO；`FefoBatch`/`DeductionPlan`/`DeductionItem`；17 项单测（FEFO 排序、跨批扣减、四舍五入到分、尾差 10.00、零成本不除零、不足抛错、双计量、流水重算、对账精确比较） |
| 4.1 流水口径库存 | `GET /inventory/ledger-stock` | 1500g 入库 + 300g 消耗 → `ledger_weight=1200.000`、`cached_weight=1200.000`、`consistency=ok` |
| 4.12 对账 | `GET /inventory/reconcile`、`POST /reconcile/repair` | 篡改缓存 -5g 后差异 `-5.000`；修复回 500.000；写 `audit_logs(action='reconcile_repair')`；复查无差异 |
| 8 项必须测试 | `tests/acceptance/test_stage4_engine.py` | 分配批次 / 不足失败 / 批量回滚 / 并发不超卖 / 撤销恢复 / 归零成本归零 / 幂等 / 调整流水 —— **10 项全绿** |
| 成本报告 | `docs/reports/cost-accounting.md` | 实跑输出：10.80 / 42.20 / 尾差 10.00 / 多批次 21.50 / 对账 0 |

**测试先行过程**：先写 27 项测试（17 纯函数 + 10 接口），确认引擎导入失败与两个新接口 404
（红），再实现到全绿。期间修正的是**测试自身**的 3 处数据错误（流水重算重复计入库、
造差异违反 `remaining <= initial` 约束），实现口径未变。

### 2.8 M6 首页与营养（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 首页汇总 | `api/v1/dashboard.py`、`services/dashboard.py` | 库存价值 42.20、期间采购 53.00 / 消耗 10.80 / 比例 0.2038、最近入库 2 条、临期 1 |
| 营养汇总 | 同上 | 消耗 300g → 热量 `495.0000`；`today/3d/week` 天数 0/2/6；`has_records` 区分空白天 |
| 空态区分 | 同上 | 无消耗时 `has_records=false`、`record_count=0`、比例为 `null`（不是 0） |
| 撤销不计入 | 同上 | 撤销一笔后 `record_count` 2 → 1 |
| 营养目标 | `api/v1/nutrition.py` | 同日重复 PUT 覆盖为 2100、库中仅 1 行、达成率 0.2357 |
| 首页 | `views/DashboardView.vue` | 空状态显示「这段时间没有消耗记录」；有数据时库存价值/批次号/495/免责声明/目标可见；1280/390 溢出 0px |

### 2.9 阶段 5 库存管理界面（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 库存总览 | `views/InventoryView.vue` | 数据源 `/inventory`；显示总量/总值/批次数；状态标签「剩 2 天 / 已过期 2 天 / 无库存」 |
| 状态筛选 | `api/v1/inventory.py` | `status=normal/expiring/expired/out_of_stock`；浏览器选「临期 7 天」→ 共 1 个食材 |
| 组合筛选 | `tests/acceptance/test_stage5_filters.py` | 搜索 + 分类 + 状态 + 位置四条件交集；拼音 + 状态组合；冲突条件返回 0 |
| 快速消耗 | `InventoryView` 弹层 | 移动端 390：点行内「− 消耗」→ 填 100 → 提交，DB 500 → 400，弹层关闭 |
| 批量消耗 | 多选 + 批量弹层 | 勾选两项填 50/60 → 批次 440/450，生成 2 张消耗单 |
| 盘点 / 报损 | `views/StocktakeView.vue` | 盘点按批次提交实际值（只发有差异行）；报损 FEFO 扣批次；下方最近记录可追溯 |
| 详情 | `IngredientDetailView` | 批次 + 单位成本 + 历史记录（20 条流水） |
| 记录 | `RecordsView` | 类型 + 日期区间 + 上一页/下一页 |

### 2.10 测试规模

```
backend/tests/
  conftest.py                    182 行   真实 PG 测试库 + 每例清库
  unit/test_pinyin.py             50 行   拼音生成 + 搜索条件（11 项）
  unit/test_batch_state.py        78 行   批次状态迁移（9 项）
  api/test_system.py              59 行   健康/信封/请求 id/日志上报（6 项）
  api/test_stage2.py             335 行   阶段 2 全部接口（25 项）
  api/test_middleware.py         150 行   CIDR + 幂等（14 项）
  api/test_batches.py            346 行   批次域（18 项）
  acceptance/test_consumption.py  ~260 行  PRD §7.1 九条验收（9 项）
  acceptance/test_inventory.py    ~250 行  库存域（14 项）
  acceptance/test_purchase.py     ~200 行  采购入库与批次（7 项）
  unit/test_inventory_engine.py   ~230 行  库存引擎纯函数（17 项，阶段 4 新增）
  acceptance/test_stage4_engine.py ~230 行 阶段 4 八项必须测试 + 4.1/4.12（10 项）
  acceptance/test_dashboard.py    ~200 行 首页汇总/营养/目标（11 项）
  acceptance/test_stage5_filters.py ~180 行 库存状态与组合筛选（7 项，阶段 5 新增）
合计 158 项，全绿
```

---

## 3. 未完成（明确列出，避免误判）

| 项 | 现状 |
| --- | --- |
| 每日对账定时任务 | `v_batch_reconcile` 已有，但 APScheduler 定时对账未启用（M7 与备份任务一起做） |
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
| K19 | 营养基准单位只接受 g/kg | 体积/「份」基准返回 `NUTRITION_BASIS_MISMATCH` | PRD §8 明确不做密度换算，属既定限制 | ℹ️ 既定限制 |
| K20 | 盘点同时改数量时只按重量计成本 | 数量差异不单独计价 | 单用户场景够用；若将来按数量核算成本需扩展 | ⚠️ 已知 |
| K21 | 对账未定时执行 | 已有 `GET /inventory/reconcile` + 修复接口，但需人工触发 | M7 与备份任务一起接入 APScheduler | ⚠️ 已知 |
| K23 | 批次详情页未内置盘点/报损入口 | 需回到食材详情页操作 | 不影响功能；批次详情已提供「记一笔消耗」与食材档案跳转 | ⚠️ 已知 |
| K22 | 盘点盘盈会改动 `batches.initial_*` 与 `purchase_cost` | 历史「初始量」不再是最初入库值 | 保持 `remaining <= initial` 约束的必要语义；变更记录在 `adjustment` 流水里 | ℹ️ 设计取舍 |

已关闭：K1~K8、K10。

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | `backend/.venv`，pytest 158 项可用 |
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
cd backend && .venv/bin/python -m pytest          # 期望 158 passed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps                                  # 期望 3 个 healthy
docker compose exec -T db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
psql -d freshkeep -tAc "select version_num from alembic_version"   # 两库应一致
```

---

## 7. 下一步（M7 备份导出与定时任务）

1. `POST /backup`：触发 `pg_dump -Fc` 到 `backups/`，返回文件名与大小；`GET /backups` 列出现有备份；
2. `GET /export/consumptions.csv`、`/export/transactions.csv`：流式 CSV，带 BOM 便于 Excel；
3. APScheduler 接入：每日 03:00 对账（`reconcile` + 自动修复有差异的批次并写审计）、
   每日备份、临期扫描；任务失败写 `audit_logs`，并在 `/dashboard/summary` 暴露最近一次结果；
4. 前端设置页加「备份 / 导出」区块与最近备份列表；
5. 补 acceptance 用例：备份文件可被 `pg_restore --list` 读取、CSV 行数与流水数一致、
   对账任务在人为制造差异后能自动修复。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-11 10:07 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `985e077` |
| 工作区 | 14 个未提交改动，未跟踪 2 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0002_ingredient_storage`，25 张表 |
| 后端测试 | 158 passed, 1 warning in 5.87s |
| 前端产物 | 已构建 |
| 文档检查 | 通过 |

最近 5 次提交：

```
985e077 2026-11-11 chore: 刷新 M6 提交后的状态快照与留痕
e98e56b 2026-11-11 feat(api): M6 首页与营养统计 —— summary/nutrition/targets + 首页改版
682ef38 2026-11-10 chore: 刷新阶段 4 提交后的状态快照与留痕
53f775d 2026-11-10 feat(api): 阶段 4 库存引擎 —— 独立纯函数层 + 流水口径库存 + 对账修复
01b3185 2026-11-10 chore: 刷新阶段 3 提交后的状态快照与留痕
```
<!-- AUTO:STATUS:END -->
