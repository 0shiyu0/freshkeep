# 开发计划

> 阶段划分与任务清单。完成情况见 `PROJECT_STATUS.md`，进度变化记入 `CHANGELOG.md`。
> 人日为「单人 + AI 辅助」口径的估算，不含需求变更与设计返工。

---

## 总览

| 阶段 | 内容 | 估时 | 状态 |
| --- | --- | --- | --- |
| 阶段 0 | 项目准备：文档、规则、骨架、数据库评审 | 2 | ✅ 完成 |
| 阶段 1 | 项目初始化：三容器可运行、前后端骨架、日志与错误处理 | 2 | ✅ 完成 |
| 阶段 2 | 基础资料管理：认证 / 分类 / 单位 / 位置 / 食材 / 图片 / 搜索 / 条码 | 3 | ✅ 完成 |
| M0 | 骨架收尾：CIDR/幂等中间件、静态托管验证、CI | 1.5 | ✅ 完成 |
| M1 | 认证：配对码 → 设备令牌（Cookie + Bearer 双通道） | 1.5 | ✅ 已在阶段 2 完成 |
| M2 | 档案域：分类 / 单位 / 位置 / 食材 / 条码 / 文件 | 3.5 | ✅ 已在阶段 2 完成 |
| M3 | 批次域：入库建批次、批次查询、状态流转 | 4 | ✅ 完成 |
| M4 | **消耗域**：FEFO、成本分摊、尾差、双计量、营养快照 | 5 | ✅ 完成 |
| M5 | 库存域：`v_inventory`、流水、详情聚合、对账任务 | 2.5 | ✅ 完成 |
| M6 | 首页与营养：dashboard、营养目标、日汇总 | 3 | ✅ 完成 |
| M7 | 备份导出：pg_dump 定时、文件备份、CSV/JSON 导出 | 1 | ⬜ 下一步 |
| M8 | 前端 5 页：配对 / 首页 / 库存 / 记录 / 设置 | 6 | ⬜ |
| M9 | 原生 App：Capacitor 集成、原生配置、双端出包 | 4 | ⬜ |
| M10 | 联调验收：9 条用例转绿、时区边界、部署手册 | 2.5 | ⬜ |
| | **P0 合计** | **36** | |

P1（临期提醒 + 盘点 + 报损 + 撤销 + 统计页 + 导出 + 扫码 + App 本地通知）≈ 12 人日。
P2（AI 识别 + 采购清单 + 菜谱 + 对账告警 + TLS）≈ 14 人日。

---

## 阶段 0 · 项目准备（已完成）

| # | 任务 | 交付物 | 完成判据 |
| --- | --- | --- | --- |
| 0.1 | 整理项目文档 | `PRD.md` `ARCHITECTURE.md` | 产品范围、业务规则、验收标准、架构与 API 无歧义 |
| 0.2 | 建立项目规则 | `AGENTS.md` | 技术栈、分层、数值精度、禁止事项可执行 |
| 0.3 | 确定技术栈 | `ARCHITECTURE.md` §2 + `requirements.txt` / `package.json` | 版本可获取且钉死 |
| 0.4 | 确定目录结构 | `backend/` `frontend/` `database/` `deploy/` `docs/` | 每层职责清晰，空目录有占位 |
| 0.5 | 初始化 Git | 仓库 + 首次提交 | 有 `.gitignore`，密钥与数据未入库 |
| 0.6 | 数据库设计评审 | `database/001_init.sql` `docs/database.md` `docs/er-diagram.md` | 25 表有用途、外键合理、对账视图为 0 |

---


## 阶段 1 · 项目初始化（已完成）

目标：能跑起来、能连上库、能看见日志。不做业务页面。

| # | 任务 | 交付物 | 完成判据 | 状态 |
| --- | --- | --- | --- | --- |
| 1.1 | Vue3 + TS + Vite 初始化 | `frontend/`、`vite.config.ts`、`tsconfig.json`、`src/main.ts` | `npm run build` 通过（vue-tsc 无错） | ✅ |
| 1.2 | FastAPI + SQLAlchemy + Pydantic 初始化 | `backend/app/{main,core,db,api}` | `/api/v1/ping` 可访问，OpenAPI 可打开 | ✅ |
| 1.3 | PostgreSQL 配置与连接池 | `db/session.py`、`/api/v1/system/db` | 返回 connected/tables/migration/pool | ✅ |
| 1.4 | Alembic 迁移 | `backend/migrations/`（`alembic.ini` 指向它） | 干净库 `upgrade head` → 25 表 + `0001_init` | ✅ |
| 1.5 | Docker 三容器 | `docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile` + `nginx.conf` | 三容器 healthy，依赖链 db→api→web | ✅ |
| 1.6 | 基础布局 | `layouts/AppLayout.vue`、`styles/main.css` | 桌面有侧边栏、移动有底部导航、顶部栏常驻 | ✅ |
| 1.7 | Axios 与统一错误处理 | `api/http.ts`、`api/index.ts`、`utils/notify.ts` | 统一 `{success,data}` 解析、错误弹提示、401 统一出口 | ✅ |
| 1.8 | 前后端日志与异常记录 | `core/logging.py`、`utils/logger.ts`、`POST /system/client-logs` | 访问日志 JSON 落 `storage/logs/api.log`；前端错误可上报 | ✅ |

**验收实测（2026-11-09）**：三容器 healthy；`GET /` 200 且资源与 SPA 回退正常；
`/api/v1/system/db` 返回 connected=true / tables=25 / migration=0001_init；
重启 db+api 后探针数据仍在；干净库跑 `alembic upgrade head` 成功。

---

## 阶段 2 · 基础资料管理（已完成）

目标：把库存业务依赖的基础数据做完整。这一层不碰流水与批次。

| # | 任务 | 交付物 | 完成判据 | 状态 |
| --- | --- | --- | --- | --- |
| 2.1 | 用户认证 | `api/v1/auth.py`、`services/auth.py`、`views/LoginView.vue`、`stores/auth.ts` | 配对码 / 密码登录 / 退出 / 改密 / 设备吊销；Web Cookie + App Bearer 双通道 | ✅ |
| 2.2 | 食材分类 | `api/v1/categories.py` | 两级增删改查 + 排序；同级重名 409；有食材时删除 409 | ✅ |
| 2.3 | 单位管理 | `api/v1/units.py` | g/kg/毫升/升/个/包/瓶/盒/袋 共 9 个内置；维度隔离；被引用拒删 | ✅ |
| 2.4 | 储存位置 | `api/v1/units.py`（loc_router） | 冷冻室/冷藏室/常温/橱柜；被引用拒删 | ✅ |
| 2.5 | 食材档案 | `api/v1/ingredients.py`、`views/{Inventory,IngredientDetail,IngredientForm}View.vue` | 新增/编辑/详情/停用；详情含分类标签、启用状态与六项属性表 | ✅ |
| 2.6 | 食材图片 | `services/files.py`、`api/v1/files.py` | 上传（魔数校验/5MB/去重）、预览（`/raw`）、删除（被引用 409） | ✅ |
| 2.7 | 食材搜索 | `services/search.py` | 中文模糊 / 全拼 / 首字母三路 OR，按「完全匹配 > 前缀 > 包含」排序 | ✅ |
| 2.8 | 条码 | `api/v1/barcodes.py` | 绑定 / 查询 / 解绑；一条码只属一个食材 | ✅ |

**验收实测（2026-11-09）**：后端 pytest 42 项全绿（含 25 项阶段 2 接口用例）；
容器上 61 项端到端断言全过；前端 vue-tsc 零错误、构建通过；
列表页与详情页在 1280 / 390 两种宽度下无横向溢出、无元素越界，侧栏↔底栏切换正确。

**本阶段用到的表**（未新增表，只补一列）：
- `file_assets` 承载图片元数据（`checksum` 唯一 → 同图不重复落盘）
- `ingredient_barcodes` 承载条码（全局唯一 → 扫码唯一定位）
- `ingredients` 补 `default_storage_location_id`（迁移 `0002`）

---

## 阶段 3 · 采购入库与批次管理（2026-11-10 完成）

本阶段与 M3 是同一块能力的两种切法：M3 交付了入库五步事务与批次数据层，
阶段 3 补齐**独立入库页面、四个日期、跨食材批次列表与批次详情页**。

| # | 任务 | 交付物 | 完成判据 | 状态 |
| --- | --- | --- | --- | --- |
| 3.1 | 入库页面 | `views/PurchaseView.vue`、路由 `/purchase` | 食材可搜索选择；数量/重量/价格/日期/位置齐全；提交后展示批次号、单位成本、流水号 | ✅ |
| 3.2 | 独立批次 | `services/inventory/__init__.py`（M3） | 每次入库生成独立批次，批次号 `yyyymmdd-NN` 递增 | ✅ |
| 3.3 | 日期管理 | `BatchCreate` 增 `opened_date` | 购买/生产/到期/开封四个日期都能保存，到期不得早于生产 | ✅ |
| 3.4 | 储存位置 | 入库表单位置下拉 | 可选冷冻室/冷藏室/常温/橱柜，也可留空 | ✅ |
| 3.5 | 成本与单位成本 | `unit_cost` 快照 | 18/500 → 0.0360、40/1000 → 0.0400，各自独立 | ✅ |
| 3.6 | purchase 流水 | 五步事务（M3） | 每次入库都写 `inventory_transactions(type=purchase)` + 分配 | ✅ |
| 3.7 | 批次列表 | `views/BatchesView.vue`、`GET /batches?q=` | 跨食材列出全部批次，支持食材名/拼音搜索、状态与位置筛选 | ✅ |
| 3.8 | 批次详情 | `views/BatchDetailView.vue` | 初始/剩余重量与数量、采购/剩余/单位成本、四个日期、位置、该批次流水 | ✅ |

**验收实测（2026-11-10）**：`tests/acceptance/test_purchase.py` 7 项全绿；
容器真实 HTTP **17 项**全过（两次采购两批次、价格独立、到期独立、四日期、位置、
单位成本 0.0360/0.0400、purchase 流水 2 条共 1500g、`q` 搜索、按 `batch_id` 查流水、
幂等不重复入库、库存总量 == 流水增量之和、对账差异 0）；
浏览器真实填表提交 500g/18 元后结果区显示批次号与 `TX-P-` 流水号；三个页面 1280/390 无溢出。

---

## 阶段 4 · 库存引擎（2026-11-10 完成）

按「测试先行」交付：先写 17 项纯函数单测 + 10 项接口验收，确认红后再实现。

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 4.1 | 基于有效流水计算库存 | `engine.recalc_from_ledger` + `GET /inventory/ledger-stock` | ✅ |
| 4.2 | FEFO 先到期先消耗 | `engine.fefo_sort_key` / `plan_deduction`（nulls last、同日期按购买日） | ✅ |
| 4.3 | 按数量或重量扣减 | `plan_deduction(mode="weight"/"quantity")` | ✅ |
| 4.4 | 多食材批量消耗 | `POST /consumptions/batch`（整批事务） | ✅ |
| 4.5 | 批次分配记录 | `transaction_allocations`（每批一条，含 unit_cost 快照） | ✅ |
| 4.6 | 按批次核算成本 | 单位成本 4 位、分摊到分、单据成本 = 分摊之和 | ✅ |
| 4.7 | 归零尾差结清 | `closes_batch` 时取剩余成本（10.00 而非 9.99） | ✅ |
| 4.8 | 盘点增减 | `POST /inventory/adjustments`（提交实际值反算 delta） | ✅ |
| 4.9 | 报损处理 | `POST /inventory/spoilage`（FEFO 扣批次） | ✅ |
| 4.10 | 撤销恢复库存 | `POST /consumptions/{id}/reverse`（反向流水） | ✅ |
| 4.11 | 行锁/事务/幂等 | `FOR UPDATE OF batches` + 请求事务 + `Idempotency-Key` | ✅ |
| 4.12 | 缓存与流水对账 | `v_batch_reconcile` + `GET /inventory/reconcile` + `POST /reconcile/repair`（写审计） | ✅ |

**测试证据**：`tests/unit/test_inventory_engine.py` 17 项、`tests/acceptance/test_stage4_engine.py` 10 项，
全量 **140 passed**；成本核算报告见 `docs/reports/cost-accounting.md`（含实跑输出）。

---

## 阶段 5 · 库存管理界面（2026-11-11 完成）

目标：端到端可用——能看、能筛、能消耗、能盘点报损、能追溯。

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 5.1 | 库存总览 | `InventoryView` 改用 `/inventory`（v_inventory 聚合） | ✅ 列表显示总量/总值/批次数，与后端一致 |
| 5.2 | 分类筛选 | 分类下拉（含子分类） | ✅ |
| 5.3 | 状态筛选 | `GET /inventory?status=` + 状态下拉 | ✅ 正常 / 临期 7 天 / 已过期 / 无库存 |
| 5.4 | 位置筛选 | 储存位置下拉 | ✅ |
| 5.5 | 食材详情 | `IngredientDetailView` | ✅ 批次 + 单位成本 + 历史流水（最近 20 条） |
| 5.6 | 快速消耗 | 列表行「− 消耗」弹层 | ✅ 移动端实测：点行内按钮 → 填 100 → 提交，DB 500→400 |
| 5.7 | 批量消耗 | 多选 + 批量弹层 → `/consumptions/batch` | ✅ 实测两项各扣 50/60，生成 2 张消耗单 |
| 5.8 | 盘点页面 | `StocktakeView`（`/stocktake` 盘点 tab） | ✅ 按批次录入实际重量，提交只发有差异的行 |
| 5.9 | 报损页面 | 同页报损 tab | ✅ 选食材 + 重量 + 原因，FEFO 扣批次 |
| 5.10 | 记录页面 | `RecordsView` 加日期筛选与翻页 | ✅ 类型 + 日期 + 上一页/下一页 |

**验收实测**：后端 `tests/acceptance/test_stage5_filters.py` 7 项全绿（状态筛选 + 四条件组合）；
浏览器实测：状态「临期」筛出 1 个食材；移动端 390 快速消耗 500→400g；
批量消耗 440/450g 且 2 张消耗单；盘点页有 tab/批次行/最近记录；详情页单位成本与历史流水可见；
记录页日期与翻页控件存在；所有页面横向溢出 0px。

---

## 阶段 6 · 首页与统计（2026-11-11 完成）

目标：把已核算准确的库存数据转成可读的统计，每个数字都能对回流水。

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 6.1 | 首页布局 | 概览卡片 + 趋势图 + 分类占比 + 排行 + 周转 + 最近操作 | ✅ `StatsPanel.vue` 接入首页 |
| 6.2 | 库存价值 | `stock.cost = Σ batches.remaining_cost` | ✅ 实测 77.20（采购总额 106.00，两者不同） |
| 6.3 | 采购统计 | `series[].purchase_amount` 按日/周/月/年 | ✅ 四种粒度，序列之和 == 总额 |
| 6.4 | 消耗统计 | `series[].consumption_amount`（含反向抵消） | ✅ 撤销后同额减少 |
| 6.5 | 分类统计 | `category_breakdown`（按消耗成本） | ✅ 各类之和 == 消耗总额 |
| 6.6 | 消耗排行 | `top_consumed`（按重量取前 10） | ✅ 300g 鸡胸肉排首 |
| 6.7 | 趋势分析 | SVG 双折线（采购/消耗） | ✅ 峰值为 Y 轴上限，X 轴首尾标签 |
| 6.8 | 库存周转 | `turnover`（采购次数/消耗次数/消耗量） | ✅ |
| 6.9 | 时间筛选 | 粒度切换 + 自定义起止 | ✅ 单日窗口只含当天；未来区间为 0 |

**口径红线**：库存价值取剩余成本，不等于采购总额；分类占比只统计消耗（不与采购重复）；
撤销走 `reverse` 流水，消耗净额自动抵消；金额全部来自流水聚合，与 `/inventory`、`/records` 可对账。

**验收实测**：`tests/acceptance/test_stats.py` 15 项全绿；容器接口 14 项全过
（106.00 / 28.80 / 77.20 与流水逐项一致；day 30 点、week 13 点、month 13 点、year 6 点；
分类占比之和 == 消耗总额；自定义单日与未来区间正确）；首页 1280/390 图表与四个粒度按钮渲染正常、无溢出。

---

## 阶段 7 · 营养管理（2026-11-11 完成）

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 7.1 | 营养项目 | `nutrition_definitions` 六项：热量/蛋白/脂肪/碳水/纤维/钠 | ✅ |
| 7.2 | 食材营养档案 | `ingredient_nutrition` 版本化（`is_current` + `version`） | ✅ 改档案旧行退役、新行 version+1 |
| 7.3 | 线性换算 | `weight × value ÷ basis_amount` | ✅ 200g × 165/100 = 330 |
| 7.4 | 营养快照 | `consumption_nutrition` 冻结值 + `basis_snapshot` | ✅ 改档案后历史不变 |
| 7.5 | 每日统计 | `/dashboard/nutrition?period=today` | ✅ |
| 7.6 | 周期统计 | `today / 3d / week / **month**` | ✅ 本月取「1 日 ~ 今天」 |
| 7.7 | 营养目标 | `GET/PUT /nutrition/targets` | ✅ 同日覆盖、历史保留 |
| 7.8 | 达标率 | `achievement = 实际 ÷ (日目标 × 天数)` | ✅ 返回 `period_target` 供展示 |
| 7.9 | 数据来源 | 档案 `source` + 快照 `basis_snapshot.source` | ✅ manual / packaging_label / database |

**验收实测**：`tests/acceptance/test_nutrition_stage7.py` 11 项全绿；容器 14 项全过：
200g 鸡胸肉 → **330 / 62 / 7.2**；改档案蛋白 30g 后历史快照仍 62、今日统计仍 62，
新消耗按新档案 60（累计 122）；month 窗口 `2026-11-01~2026-11-11`（days=10），
达成率按 `2000×11` 换算；详情页显示「手动录入 / 包装标识」，编辑弹层真实保存 160 且历史快照仍 330。

**口径声明**：所有营养值是**按库存消耗量推算**，不等于实际摄入体内的量；前端在
有记录与空态两种情况下都展示该说明。

---

## 阶段 8 · 智能辅助（2026-11-11，进行中）

**硬约束**：AI 识别只写 `recognition_drafts`，禁止直接改库存；确认后才建档/入库。

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 8.1 | 条码扫描 | `ScanView`：`BarcodeDetector` + 摄像头；不支持时手动输入兜底 | ✅ |
| 8.2 | 条码查询 | `GET /products/lookup`：本地 `ingredient_barcodes` 优先 | ✅ |
| 8.3 | 外部商品源 | `GET/PUT /products/source`：none / openfoodfacts / custom，拒绝内网地址 | ✅ |
| 8.4 | 图片识别 | `POST /ai/recognitions` + 拍照上传 → 草稿 | ✅ |
| 8.5 | 营养表识别 | provider 返回 nutrition 数组，规范化后进草稿 | ✅ |
| 8.6 | 日期识别 | 生产/到期/保质期；`DATE_SWAPPED` 等 5 类校验 | ✅ |
| 8.7 | 临期扫描 | `POST /alerts/scan`：幂等 SQL（expiring/expired/low_stock） | ✅ 手动触发；定时任务待接 |
| 8.8 | 临期提醒 | `/alerts` 通知中心 + 首页入口；**按需求范围只做应用内通知，不做系统级推送** | ✅ 完成（范围收敛） |
| 8.9 | 最低库存 | `ingredients.minimum_quantity/minimum_weight` + `is_low_stock` | ✅ 已有 |
| 8.10 | 采购建议 | `GET /purchase/suggestions`：最低库存差额 / 近 30 天用量估算 | ✅ |
| 8.11 | 菜谱管理 | `GET/POST /recipes`、`GET/PUT/DELETE /recipes/{id}`；**步骤已结构化**（`recipe_steps`，兼容旧文本）；前端 `RecipesView` | ✅ |
| 8.12 | 菜谱匹配 | `GET /recipes/{id}/match?servings=`：需求（按份缩放）− 库存 → 缺口 | ✅ |
| 8.13 | 采购清单 | `POST /shopping-lists/from-recipes`：需求相加后减库存，只留缺口；`ShoppingListsView` | ✅ |

**8.11~8.13 实测**：`tests/acceptance/test_recipes.py` 14 项全绿（CRUD/校验/按份缩放/缺口/合并清单/不产生流水）；
容器 13 项全过：700g 需求 − 500g 库存 = 200g 缺口、4 份需 600g 缺 100g、
清单生成前后流水数不变；三个页面 1280/390 均无溢出。

**已完成部分实测**：`tests/acceptance/test_ai_assist.py` 16 项全绿（含"识别/修正/拒绝三个阶段批次与流水零变化"的硬断言）；
容器真实 HTTP 26 项全过；浏览器 390 实测手动链路：查询未命中 → 手动填写 → 待确认（含 `NAME_MISSING`）
→ 填名 → 确认建档 → 跳转详情，DB 已创建；提醒页扫描后出现低库存通知与采购建议。

**日期误识别处理**：生产晚于到期 → 自动交换 + `DATE_SWAPPED`；只有到期且已过期 → `EXPIRY_IN_PAST`；
生产 + 保质期 → 推算并标 `EXPIRY_DERIVED`；两日期相同 → `SAME_DAY_FILLED`；超范围 → `DATE_OUT_OF_RANGE`。
确认时若有日期告警，前端二次确认。

---

## 阶段 9 · 部署上线（2026-11-11）

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 9.1 | PWA 配置 | `frontend/public/manifest.webmanifest`（含 shortcuts/icons）、`index.html` PWA meta、`main.ts` 注册 SW | ✅ |
| 9.2 | 手机端适配 | `main.css` 安全区 / `100dvh` / 16px 输入防缩放 / touch-action；1280 与 390 双端 DOM 探针 | ✅ |
| 9.3 | 离线基础页面 | `public/offline.html` + `sw.js`（API 与写操作不缓存、导航 network-first 回退离线页） | ✅ |
| 9.4 | 通知权限 | `utils/notifications.ts` + 设置页申请/开关/测试；提醒页扫描后可选发送；**默认关闭，需显式授权** | ✅ |
| 9.5 | HTTPS | `frontend/nginx.https.conf`（443 + 安全响应头 + HSTS/CSP）、`docker-compose.https.yml`、自签证书脚本 | ✅ |
| 9.6 | NAS Docker 部署 | `scripts/deploy-nas.sh`；三容器跑在 NAS `192.168.31.198`，独立端口 18080/18443 | ✅ |
| 9.7 | 自动备份 | `ENABLE_SCHEDULER=true` 三作业 + `prune_backups(keep=7)` 保留策略 | ✅ |
| 9.8 | 恢复演练 | `scripts/restore_drill.py`：备份 → 临时库 → schema → 27 表 COPY → 逐表核对 → 删演练库 | ✅ |
| 9.9 | 安全和性能验收 | `scripts/stage9_acceptance.py`：凭据扫描 / HTTPS 头 / 鉴权 / p95 延迟 / PWA 资产 | ✅ |

**边界**：8.8 阶段曾按需求收敛为「应用内通知中心、不做系统级推送」；阶段 9 的 9.4 是**用户显式授权后才可选的浏览器通知**，
默认关闭、不改动任何库存逻辑，两者不冲突。

**凭据处理**：NAS 账户密码只在本次会话的临时文件中使用（`/tmp/fk_nas_pass` 与 NAS `/tmp/.fk_pw`），
用后删除；未写入源码、日志、`.env` 或版本库（验收脚本逐文件扫描确认 0 命中）。

---

## M0 · 骨架收尾（已完成）

| # | 任务 | 完成判据 | 状态 |
| --- | --- | --- | --- |
| 0.1 | 三容器跑通 | `/health` 返回 `db:true`，3 个容器 healthy | ✅ |
| 0.2 | 迁移在真库执行 | `alembic current` → `0002_ingredient_storage (head)` | ✅ |
| 0.3 | `ALLOW_CIDR` 中间件 | 公网 IP 403、局域网/组网/回环放行 | ✅ |
| 0.4 | 统一响应与错误处理 | 参数错误 → `VALIDATION_ERROR` 且含 `request_id` | ✅ |
| 0.5 | 静态托管 | `/` 返回 SPA，`/api/v1/*` 不被兜成 HTML | ✅ |
| 0.6 | 幂等中间件 | 同 key 同 body 返回原响应；不同 body 409 | ✅ |
| 0.7 | CI | push 触发 pytest + 前端构建 + 文档检查 | ✅ |


| # | 任务 | 完成判据 |
| --- | --- | --- |
| 0.1 | `docker compose up -d` 在 NAS 上跑通 | `/health` 返回 `{"status":"ok","db":true}` |
| 0.2 | Alembic 迁移在真库执行 | `alembic current` → `0001_init (head)`；25 表存在 |
| 0.3 | `ALLOW_CIDR` 中间件 | 非白名单 IP 返回 403；白名单放行 |
| 0.4 | 统一响应与错误处理 | 参数错误返回 `VALIDATION_ERROR` 且含 `request_id` |
| 0.5 | 静态托管 | `npm run build` 后 `/` 返回 SPA，`/api/v1/*` 不被兜住 |
| 0.6 | 幂等中间件 | 同 `Idempotency-Key` 同 body 返回原响应 |
| 0.7 | CI 基础 | push 触发 `pytest` + `npm run build` 通过 |

**验收**：本地/ NAS 上 `curl` 六个接口返回预期 JSON；`pytest` 全绿。

---

## M1 · 认证（已由阶段 2.1 交付）

配对码生成（CLI）→ `/auth/pair` → 设备令牌 → Cookie/Bearer 双通道 → 设备列表与吊销 → 登录限流。

**完成判据**：浏览器输入配对码后可访问受保护接口；App 用 Bearer 可访问；吊销后 1 秒内失效；
重复使用同一配对码返回 401。

---

## M2 · 档案域（已由阶段 2.2~2.8 交付）

分类（两级，同级不重名）→ 单位（dimension 隔离）→ 储存位置 → 食材（含拼音索引）→ 条码 → 文件上传。

**完成判据**：能建档、能按中文/拼音/首字母搜到；改营养档案生成新版本且旧版本 `is_current=false`；
条码重复绑定被拒。

---

## M3 · 批次域（2026-11-09 完成）

入库（同一事务写 `purchase` 流水 + 分配）→ 批次列表/详情 → 临期与过期查询 → 状态流转。

| # | 任务 | 完成判据 | 状态 |
| --- | --- | --- | --- |
| 3.1 | ORM / schema | `Batch`、`InventoryTransaction`、`TransactionAllocation` 三个映射；请求/响应模型 | ✅ |
| 3.2 | `POST /batches` 五步事务 | 同事务写 `purchase` 流水 + 自分配 + 批次缓存，并断言 `Σ分配 == 流水delta` | ✅ |
| 3.3 | 查询接口 | `GET /batches`、`/{id}`、`/expiring`、`/expired` | ✅ |
| 3.4 | 状态机 | `services/inventory/state.py`：归零自动 depleted、恢复库存回 active、禁止直接改状态 | ✅ |
| 3.5 | 元数据保护 | `PUT /batches/{id}` 改元数据可用；带 `remaining_*`/`purchase_cost`/`status` 一律 400 | ✅ |
| 3.6 | 前端 | 食材详情页批次列表 + 入库表单（双计量、位置、到期日） | ✅ |

**完成判据实测**：`v_batch_reconcile` 三个 diff 均为 `0.000/0.000/0.00`；
`unit_cost=0.0360`（18 元 ÷ 500g）；容器真实 HTTP 18 项断言全过；
pytest 83 项全绿；详情页 1280/390 两种宽度无横向溢出。

---

## M4 · 消耗域（2026-11-09 完成）

FEFO 分配 → 成本分摊 + 尾差 → 双计量联动 → 事务边界 → 营养快照 → 批量消耗 → 撤销。

| # | 任务 | 完成判据 | 状态 |
| --- | --- | --- | --- |
| 4.1 | `tests/acceptance/` 建立并先写失败测试 | PRD §7.1 的 9 条用例先全红，再实现到全绿 | ✅ |
| 4.2 | FEFO + `FOR UPDATE` 行锁 | 两线程同时扣 400g（总量 500g）→ 201/422，余额不为负；去掉行锁测试变红 | ✅ |
| 4.3 | 成本分摊与尾差结清 | 300g → 10.80；批次扣完时剩余成本归 0；剩余库存成本 42.20 | ✅ |
| 4.4 | 双计量 | 只给数量按换算折算或按数量维度扣减；两维度不自洽 422；无换算关系禁止推算 | ✅ |
| 4.5 | 营养快照 | 300g × 165kcal/100g = 495；改档案到 170 后历史仍 495、新消耗 340 | ✅ |
| 4.6 | 批量消耗 | 一项库存不足整批 422，且不产生任何部分消耗单 | ✅ |
| 4.7 | 撤销 | `reverse` 流水 + 反向分配 + 恢复余额 + 原记录 `reversed` 保留 | ✅ |
| 4.8 | 前端 | 消耗录入页（FEFO 结果/成本/营养）、记录页（状态筛选/撤销） | ✅ |

**完成判据实测**：9 条验收全绿（pytest 92 passed）；容器真实 HTTP 22 项全过；
浏览器真实点击提交消耗后结果区显示 ¥3.60 与批次分配；对账 diff 始终为 0。
本轮**无 DDL 变更**，迁移版本仍为 `0002_ingredient_storage`。

> 做法已按计划执行：先把 9 条用例写成**失败测试**（确认 9 failed），再实现到全绿。

---

## M5 · 库存域（2026-11-10 完成）

`v_inventory` 查询与筛选 → 流水分页 → 食材详情聚合 → 盘点 / 报损。

| # | 任务 | 完成判据 | 状态 |
| --- | --- | --- | --- |
| 5.1 | `GET /inventory` | 读 `v_inventory`，支持中文/拼音搜索、分类（含子分类）、位置、低库存筛选与分页 | ✅ |
| 5.2 | `GET /inventory/summary` | 总重量/总成本/食材数/批次数/低库存数/临期 7 天/已过期 | ✅ |
| 5.3 | `GET /inventory/transactions` | 全部流水，类型/食材/日期过滤 + 分页；响应含 `related_object_id` 供撤销 | ✅ |
| 5.4 | `POST /inventory/adjustments` | 提交实际值反算 delta；盘亏按单位成本扣、归零结清尾差；盘盈同步上调 initial 与采购成本 | ✅ |
| 5.5 | `POST /inventory/stocktake` | 批量盘点，任一项非法整批回滚 | ✅ |
| 5.6 | `POST /inventory/spoilage` | 报损按 FEFO 扣批次，写 `spoilage` 流水；必填原因 | ✅ |
| 5.7 | 前端 | 记录页接完整流水（类型筛选 + 消耗撤销）；库存页汇总条；详情页盘点/报损弹层 | ✅ |

**完成判据实测**：`v_batch_reconcile` 在盘点/盘盈/报损后差异始终为 0；
`tests/acceptance/test_inventory.py` 14 项全绿；容器真实 HTTP 16 项全过；
三个页面 1280/390 DOM 探针无溢出。**对账任务（每日定时）尚未实现**，留到 M7 与备份任务一起做。

**本轮无 DDL 变更**，迁移版本仍为 `0002_ingredient_storage`。

---

## M6 · 首页与营养

dashboard 五组接口 → 营养定义/目标 → 日汇总（区分"无记录"与"0 摄入"）。

**完成判据**：首页四个数字与手工核对一致；营养卡片标注"按库存消耗量估算"。

---

## M7 · 备份导出与定时任务（2026-11-11 完成）

| # | 任务 | 交付物 | 状态 |
| --- | --- | --- | --- |
| 7.1 | 备份 | `POST /backup` → `freshkeep-backup-<ts>.tar.gz`（`schema.sql` + 27 张表 CSV + `manifest.json`） | ✅ |
| 7.2 | 备份管理 | `GET /backups`、`POST /backups/{name}/verify`、`GET /backups/{name}/download`（拒绝路径穿越） | ✅ |
| 7.3 | 导出 | `GET /export/transactions.csv`、`/consumptions.csv`，流式 + BOM | ✅ |
| 7.4 | 定时任务 | `app/tasks/scheduler.py`：03:00 对账、03:10 备份、08:00 临期扫描；`ENABLE_SCHEDULER=true` 启用 | ✅ |
| 7.5 | 前端 | 设置页「备份与导出」：立即备份、列表、校验、下载、CSV、任务状态与手动执行 | ✅ |

**实现取舍**：api 镜像是 `python:3.12-slim`，没有 `pg_dump`；装 `postgresql-client` 只有 PG15
（导出 PG16 会直接报版本不兼容）。因此改为**纯 Python 逻辑备份**（`COPY ... TO STDOUT` + tar.gz），
恢复方式：建库 → `psql -f schema.sql` → 按表 `COPY FROM`。宿主机仍可用 `deploy/backup.sh` 做物理备份。

**完成判据实测**：备份 27 张表 / 139 行、`verify.ok=true`、下载返回 `application/gzip`、
路径穿越 404；CSV 带 BOM 且表头正确；容器内 `enabled=true / running=true`，手动执行对账与扫描均写
`audit_logs(scheduler_*)`。

---

## M8 · 前端页面（2026-11-11 完成）

配对页 → 首页 → 库存（含批次详情）→ 记录 → 设置（设备/分类/单位/目标/备份）。

| 页面 | 状态 |
| --- | --- |
| 登录（配对码/密码） | ✅ `LoginView` |
| 首页 | ✅ `DashboardView` + `StatsPanel`（统计/营养） |
| 库存总览 | ✅ `InventoryView`（四条件筛选、快速/批量消耗） |
| 食材详情 / 新增 / 编辑 | ✅ `IngredientDetailView`、`IngredientFormView` |
| 批次列表 / 批次详情 | ✅ `BatchesView`、`BatchDetailView` |
| 采购入库 | ✅ `PurchaseView` |
| 消耗录入 | ✅ `ConsumeView` |
| 盘点 / 报损 | ✅ `StocktakeView` |
| 记录 | ✅ `RecordsView`（类型/日期/翻页/撤销） |
| 设置 | ✅ `SettingsView`（备份区块随 M7 一起加） |

**完成判据**：手机浏览器全流程可用（阶段 5 已实测移动端消耗）；三态（加载/空/错误）在库存、
批次、记录、首页四个列表页均有；401 由 `AppLayout` 的全局 handler 跳登录。

**遗留**：`PairView.vue` 无引用，可删除。

---

## M9 · 原生 App（工程脚手架已就绪，平台目录待生成）

| 项 | 现状 |
| --- | --- |
| Capacitor 配置 | ✅ `frontend/capacitor.config.ts`：`appId=com.0shiyu0.freshkeep`、`webDir=dist`、`androidScheme='http'`、`cleartext=true` |
| 插件依赖 | ✅ core/app/network/preferences/splash-screen/status-bar/local-notifications + secure-storage（已在 `package.json`） |
| 平台包 | ✅ `@capacitor/android@8.6.0`、`@capacitor/ios@8.6.0` 已装入 `package.json` 并生成 `android/` 平台（iOS 需 Xcode，目录未生成） |
| 平台目录 | ✅ `frontend/android/` 已生成并入库（含 cleartext 与 CAMERA 权限）；`ios/` 需 Xcode 未生成 |
| 一键脚本 | ✅ `scripts/cap-add-platforms.sh`：install 平台包 → build → `cap add android/ios` → `cap sync` |
| 原生配置 | ✅ Android：`AndroidManifest.xml` 已加 `usesCleartextTraffic` 与 `CAMERA` 权限；iOS 待生成后补 `NSCameraUsageDescription` + `NSAllowsArbitraryLoads` |
| App ID | ✅ 修正为 `com.shiyu.freshkeep`（原 `com.0shiyu0.*` 段以数字开头，Android 校验不通过） |
| 出包验收 | ✅ APK（4.4MB）与 iOS 真机构建均完成；iOS 签名 Personal Team 6H3GBQA9X6，7 天有效期需 Xcode 续签 |

**为什么平台包不进 `package.json`**：加进 `dependencies` 会让 `docker compose build web` 在构建时
联网安装这两个包，而镜像构建环境无外网，实测直接失败。平台包属于「打包期依赖」，
由脚本在本地按需安装（`--save`），Web 产物与原生工程解耦。

**执行方式**：在有网络的机器上 `./scripts/cap-add-platforms.sh`；iOS 需完整 Xcode（本机仅 CLT）。

---

## M10 · 联调验收

9 条用例端到端跑绿 → 时区与边界 → 部署手册 → 备份恢复演练。

**完成判据**：`PROJECT_STATUS.md` 的"已知问题"清空或全部有处置说明。

---

## P1 待排期

临期提醒（含 App 本地通知排程）· 盘点批量 · 报损 · 撤销入口 UI · 统计页图表 · 导出中心 · 条码扫描 · 开封后保质期。

## P2 待排期

AI 图片/营养表识别（结果仅作草稿）· 采购清单（含菜谱缺口合并）· 菜谱管理 · 对账告警 · 自签 TLS（可选）。
