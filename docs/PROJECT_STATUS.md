# 项目状态

> 快照时间：2026-11-11 18:50（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `docs/CHANGELOG.md`。

---

## 1. 一句话现状

**阶段 9 部署上线完成（9/9）**：PWA / 手机端适配 / 离线基础页 / 通知权限 / HTTPS /
NAS Docker 部署 / 自动备份 / 恢复演练 / 安全与性能验收全部落地。
服务已部署到 NAS `192.168.31.198`（HTTP 18080、HTTPS 18443），三容器健康；
pytest **232 项通过**（含清单一键入库），NAS 三容器 healthy，恢复演练 27 表逐表核对通过，版本库凭据扫描 0 命中。
本机库与 NAS 库均为 `0004_recipe_steps`（测试库版本登记为 `0001_init`，结构由 `001_init.sql` 全量建表、与最新一致），业务表 27 张；**AI 只写草稿表**，备份与采购清单不产生库存流水。

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
| **阶段 6 首页统计** | ✅ **完成** | stats/overview + 趋势/占比/排行/周转 + 首页面板；证据见 §2.10 |
| **阶段 7 营养管理** | ✅ **完成** | 项目/档案版本/快照/四周期/目标达标率/来源；证据见 §2.11 |
| **阶段 8 智能辅助** | ✅ **完成** | 8.1~8.13 落地；8.8 按范围只做应用内通知；证据见 §2.12 |
| **M7 备份导出与定时任务** | ✅ **完成** | 逻辑备份 + CSV + APScheduler 三作业；证据见 §2.13 |
| **M8 前端页面** | ✅ **完成** | 13 个视图：登录/首页/库存总览/食材详情与编辑/批次列表与详情/采购入库/消耗录入/盘点报损/记录/设置；401 由全局 handler 跳登录 |
| **阶段 9 部署上线** | ✅ **完成** | 9/9：PWA/移动端/离线/通知/HTTPS/NAS/备份/演练/验收；证据见 §2.16 |
| M9 原生 App | ✅ **完成** | APK 已出（debug 4.4MB）；iOS 真机构建签名通过（Personal Team 6H3GBQA9X6）；证据见 §2.14 |
| M10 联调验收 | ✅ **完成** | 本次在 NAS 完成部署联调与安全/性能验收；证据见 §2.16 |

整体进度：**阶段 0~9 全部完成，M0~M8、M10 完成；M9 仅剩原生平台目录与 APK/IPA 出包（需联网）**。按人日约 35.5/36。

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

### 2.10 阶段 6 首页与统计（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 统计接口 | `api/v1/stats.py`、`services/stats.py` | 一次返回库存价值/总额/序列/分类/排行/周转/最近操作 |
| 库存价值 | 同上 | `Σ remaining_cost` = 77.20，采购总额 106.00，两者不等 |
| 采购/消耗 | 同上 | 106.00 / 28.80 与流水逐项一致；撤销后消耗净额减少 |
| 粒度 | 同上 | day 30 点 / week 13 点 / month 13 点 / year 6 点；序列之和 == 总额 |
| 时间筛选 | 同上 | 单日窗口只含当天；未来区间 0 且 `has_data=false`；起止倒置返回 400 |
| 分类占比 | 同上 | 肉类 10.80 + 蔬菜 2.00 == 消耗总额；比率之和 ≈ 1 |
| 排行/周转 | 同上 | 鸡胸肉 300g 居首；采购 2 次/消耗 2 次 |
| 首页 | `components/StatsPanel.vue` | 4 卡 + SVG 折线 + 占比条 + 排行条 + 周转表 + 最近操作；1280/390 溢出 0px |

### 2.11 阶段 7 营养管理（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 7.1 项目 | `nutrition_definitions` | 六项齐全（热量/蛋白/脂肪/碳水/纤维/钠），单位正确 |
| 7.2 档案版本 | `api/v1/ingredients.py` | 改档案后旧行 `is_current=false`、新行 version=2 |
| 7.3 换算 | `services/consumption` | 200g × 165/100 = 330；蛋白 62、脂肪 7.2 |
| 7.4 快照 | `consumption_nutrition` | 改档案蛋白 30g 后历史快照仍 62、今日统计仍 62；新消耗 60 |
| 7.5/7.6 周期 | `services/dashboard.py` | today / 3d / week / **month**（2026-11-01~今天） |
| 7.7 目标 | `GET/PUT /nutrition/targets` | 同日覆盖为 2100、库中仅 1 行 |
| 7.8 达标率 | 同上 | 按 `日目标 × 天数`：3d 用 6000、month 用 22000 作分母 |
| 7.9 来源 | `ingredient_nutrition.source` | manual / packaging_label / database；非法值 400 |
| 前端 | 详情页 + 首页 | 来源标签、编辑弹层真实保存（热量 160 落库）、首页四个周期按钮 |

### 2.12 阶段 8 智能辅助（上，本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 草稿闸门 | `services/ai/__init__.py`、迁移 `0003` | 识别/修正/拒绝后 `batches` 与 `inventory_transactions` 计数不变（测试硬断言） |
| 日期误识别 | `services/ai/validate.py` | 生产晚于到期 → 自动交换 + `DATE_SWAPPED`；5 类告警 |
| 确认建档 | `POST /ai/recognitions/{id}/confirm` | 食材 + 营养 + 拼音；`audit_logs(recognition_confirm)` |
| 确认入库 | 同上（target=batch） | 复用五步事务：批次 +1 / 流水 +1 / 对账 0 |
| 条码查询 | `GET /products/lookup` | 本地命中 `source=local`；未命中且无源 → `none` |
| 外部源 | `GET/PUT /products/source` | 内网地址返回 `source_error`（SSRF 防护） |
| 临期扫描 | `POST /alerts/scan` | 三条 `INSERT ... WHERE NOT EXISTS`；第二次 `created=0` |
| 通知中心 | `/alerts` 前端 | 统计卡 + 列表 + 已读；390 实测出现低库存项 |
| 采购建议 | `GET /purchase/suggestions` | 最低 1000/现有 200 → 建议 800g、预估 ¥28.80（字符串） |
| 扫码/待确认 | `ScanView` | 390 实测：查询→手动填写→`NAME_MISSING`→填名→确认建档→跳详情，DB 落库 |
| 8.11 菜谱 | `api/v1/recipes.py`、`RecipesView` | CRUD + 整体替换食材 + 搜索；详情带当前库存 |
| 8.12 匹配 | `GET /recipes/{id}/match` | 1 份 150g（基准 2 份 300g）；4 份需 600g 缺 100g；数量无换算标 `unmeasured` |
| 8.13 清单 | `POST /shopping-lists/from-recipes` | 两菜谱 700g 需求 − 500g 库存 = 200g 缺口；牛奶无缺口不出现；流水 2→2 不变 |
| 菜谱页面 | `RecipesView`/`RecipeDetailView`/`ShoppingListsView` | 三页 1280/390 渲染匹配表、缺口、步骤、清单项；溢出 0px |

### 2.13 M7 备份导出与定时任务（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 逻辑备份 | `services/backup.py` | `POST /backup` → tar.gz（`schema.sql` + 27 表 CSV + manifest），27 表 / 139 行，sha256 64 位 |
| 备份管理 | `api/v1/backup.py` | 列表、`verify.ok=true`、下载 `application/gzip`、`../x.tar.gz` 返回 404 |
| CSV 导出 | `services/export.py` | 流水/消耗两个导出均带 BOM；表头正确；容器库含历史行 |
| 定时任务 | `app/tasks/scheduler.py` | 容器内 `enabled=true / running=true`；三作业可手动执行；写 `audit_logs(scheduler_*)` |
| 前端 | `SettingsView` | 「备份与导出」区块：立即备份/列表/校验/下载/CSV/任务状态；1280/390 溢出 0px |

### 2.14 M9 Capacitor（Android 已生成）

| 项 | 现状 |
| --- | --- |
| 配置 | `capacitor.config.ts`：appId=`com.shiyu.freshkeep`（已修正，原段以数字开头不合法）/ webDir=dist / androidScheme=http / cleartext=true |
| 插件 | core/app/network/preferences/splash-screen/status-bar/local-notifications + secure-storage；平台包 `@capacitor/android|ios@8.6.0` 已装 |
| 平台 | ✅ `frontend/android/` 已生成入库；`AndroidManifest.xml` 已加 `usesCleartextTraffic` 与 `CAMERA` 权限；`cap sync` 通过 |
| iOS | ⬜ 需 Xcode（本机仅 CLT）；生成后补 `NSCameraUsageDescription` + `NSAllowsArbitraryLoads` |
| 出包 | ✅ APK：`gradlew assembleDebug` → app-debug.apk 4.4MB（用户已装 Android 真机）；iOS：真机构建签名通过，App ID com.shiyu.freshkeep |
| 脚本 | `scripts/cap-add-platforms.sh` 保留（iOS 复用） |

### 2.16 阶段 9 部署上线（本轮）

| 项 | 文件 / 位置 | 验证方式与结果 |
| --- | --- | --- |
| PWA | `frontend/public/manifest.webmanifest`、`sw.js`、`offline.html`、`icons/` | 构建产物含 4 类资产；`index.html` PWA meta；`main.ts` 正式构建注册 SW |
| 手机端 | `styles/main.css`、各视图 | 1280/390 双端 DOM 探针：安全区、`100dvh`、16px 输入、无横向溢出 |
| 离线基础页 | `public/offline.html` | 明确「离线不记消耗/盘点/入库」；SW 对 `/api/` 与写操作完全不拦截 |
| 通知权限 | `utils/notifications.ts`、设置页、提醒页 | 申请/开关/测试通知；默认关闭、需显式授权；不改动库存逻辑 |
| HTTPS | `nginx.https.conf`、`docker-compose.https.yml`、自签证书脚本 | 443 + TLSv1.2/1.3 + HSTS/CSP/X-Frame-Options 等；证书 SAN 含 NAS IP；证书不入库 |
| NAS 部署 | `/vol1/docker/freshkeep`（NAS `192.168.31.198`） | 三容器 healthy；HTTP 18080 / HTTPS 18443；entrypoint 自动迁移与种子 |
| 自动备份 | `prune_backups(keep=7)` + APScheduler 三作业 | 保留最近 7 份；`/tasks` 显示启用与运行；作业写 `audit_logs` |
| 恢复演练 | `scripts/restore_drill.py` | 临时库恢复 27 表、逐表行数一致、演练库自动删除；修复了 schema 路径与 COMMIT 两个缺陷 |
| 安全与性能 | `scripts/stage9_acceptance.py` | 凭据 0 命中、HTTPS 安全头、API 401 鉴权、p95 延迟、容器健康 |

### 2.19 v1.0.0 镜像构建与打包（2026-11-12）

| 项 | 结果 |
| --- | --- |
| 镜像 | `freshkeep-api:1.0.0` = `683a79575c17`（**77.6MB**，原 337MB → 瘦身 77%）；`freshkeep-web:1.0.0` = `3e74d5ade098`（21.4MB）；均 `linux/amd64` |
| 发布包 | `releases/freshkeep-1.0.0-amd64.tar.gz` 94MB，SHA-256 `982ae6a4…134a`，`docker load` 可载入 2 个镜像 |
| api 可用性 | 依赖导入正常（fastapi/sqlalchemy/psycopg 版本已核）；`import app.main` 成功，OpenAPI **85 路径** |
| web 可用性 | 产物含 index/manifest/offline/icons + **45 个 assets**；静态资源全部 **200** |
| 已知属性 | web 的 nginx 在**启动时**硬解析 upstream `api`，脱离 api 单独 `docker run` 会 exit 1（compose 有 `depends_on`，正常部署无影响） |
| GHCR | ⬜ **未推送**：环境无 `gh` CLI / `GITHUB_TOKEN` / ghcr 登录；推送命令已写入 `releases/README.md` §6 |
| 仓库可见性 | GitHub 仓库已为 **public**，本地与远程同步（0/0） |

### 2.18 阶段 3：文档与部署配置、代码质量规范化（2026-11-12）

| 项 | 交付 | 证据 |
| --- | --- | --- |
| 文档 | 新增 `ENVIRONMENT.md`（变量字典）、`DEPLOYMENT.md`（NAS 部署+升级）、`BACKUP_RESTORE.md`、`ROLLBACK.md`；`ARCHITECTURE.md` 补 §10 部署拓扑与持久化；`README.md` 重写（技术栈/功能/架构/目录/环境变量/部署） | `check-docs` 内链全通过 |
| Dockerfile | 后端：依赖层与代码层分离、`PYTHONFAULTHANDLER`、`STOPSIGNAL`、说明非 root 取舍；前端：`EXPOSE 80 443`、`STOPSIGNAL SIGQUIT`、类型检查纳入构建 | `docker compose config -q` 通过 |
| Compose | db 加 `shm_size: 128mb` + `mem_limit 512m`、api `768m`、web `128m`；三服务日志轮转 `10m×3`；`stop_grace_period` 30/20/10s | `docker compose config` 可见全部字段 |
| 持久化核查 | `pgdata`/`storage`/`backups` 三处 bind mount，容器重建与镜像升级均不影响 | 见 `ARCHITECTURE.md` §10.2 |
| lint/format | `backend/pyproject.toml`（ruff：E/F/I/UP/B/SIM/RUF，line-length 100）+ `frontend/.prettierrc` + `.prettierignore` + `lint`/`format`/`format:check` 脚本 | `ruff check app tests` **全过**（原 299 → 0）；prettier 31 文件统一 |
| 覆盖率基线 | `backend/pytest.ini`：`--cov=app --cov-fail-under=80` | 实测 **87.15%**，门槛 80%，生成 `coverage.xml` |
| 测试库版本 | `conftest.py` 改为动态读 `ScriptDirectory.get_current_head()`，不再硬编码 `0001_init`；`test_system` 断言同步改为动态 | 测试库 `alembic_version` 现为 `0004_recipe_steps` |
| 路由校验 | 22 文件 / 85 路径逐项审计：整改 `ingredients` 分页无界 + `sort_by` 白名单、`backup.job_id` 改 `Literal`；3 类"有意不分页"确认合理 | `docs/API_VALIDATION_AUDIT.md` |

验证：`pytest 232 passed`（覆盖率 87.08%）、`ruff` 0 问题、前端 `vue-tsc + vite build` 通过、
`docker compose config` 合法。

### 2.17 V1.0.0 发布准备 · 阶段 1：现状审计与备份（2026-11-12）

**审计结论（全部由命令实测，非文档推断）**

| 维度 | 实测结果 |
| --- | --- |
| 代码规模 | 后端 69 文件 / 10142 行；测试 23 文件 / 4338 行；前端 45 文件 / 6410 行 TS+Vue + 300 行 CSS；DDL 539 行 |
| 路由 | OpenAPI 85 条路径；22 个 APIRouter 文件；21 个服务文件；22 个 ORM 类 |
| 前端 | 17 个视图；`public/` 5 个 PWA 资产；构建 2808 modules / 507ms 可复现 |
| 数据库 | 27 张业务表 + 2 个视图（`v_inventory`、`v_batch_reconcile`）；迁移链 0001→0002→0003→0004 线性无分叉 |
| 本机库 | `0004_recipe_steps`，**27 表全部 0 行**（本机为空库，仅开发用） |
| NAS 库 | `0004_recipe_steps`；ingredients=2 / batches=2 / transactions=3 / consumptions=1 / users=1 / devices=2，其余 0 |
| Git | 远程 `git@github.com:0shiyu0/freshkeep.git`；单分支 `main`；**46 提交**（2026-11-08 起）；**无 tag**；工作区仅 `commits.log` |
| NAS 容器 | `freshkeep-web/api/db` 均 healthy，运行 14h；端口 18080/18443 |
| NAS 镜像 | `freshkeep-api:latest` af78090822c9 234MB；`freshkeep-web:latest` a3f01b25f6b4 49.2MB（**本地构建、无版本标签**） |
| 数据卷 | `pgdata` 65M、`storage` 648K、`backups` 52K；挂载 backups/storage/logs 三处 |
| 附件存储 | `storage/uploads` **为空**，`file_assets`=0（无图片需迁移） |
| 测试 | `pytest` **232 passed**（实跑）；前端构建通过 |
| 定时任务 | **03:10 自动备份已产出** `freshkeep-backup-20261112-031000.tar.gz`（自动触发已得证据） |

**阶段 1 备份产物**（`backups/v1.0.0-pre/`，已 gitignore）

| 文件 | 大小 | 校验 |
| --- | --- | --- |
| `local-freshkeep-20261112-140930.dump` | 85K | `pg_restore -l` 28 个表数据段 |
| `nas-freshkeep-20261112-140930.dump` | 90K | 28 个表数据段；恢复到临时库抽查 ingredients=2 / batches=2 一致 |

**审计发现的待处理项（留待后续阶段，本次不改代码）**

1. 根目录 9 个**遗留静态站文件**仍在版本库（`css/style.css`、`js/app.js`、`js/store.js`、`index.html`、`manifest.webmanifest`、`sw.js`、`icons/*`、`tests/selftest.html`），与 `frontend/` 重复，发布前需决策保留或删除。
2. `PROJECT_STATUS §3/§7` 与末尾自动快照滞后（详见 §3 顶部说明）。
3. NAS 镜像只有 `latest` 标签、无版本号与 digest 固定，V1.0.0 需改为 `ghcr.io/0shiyu0/freshkeep-api:1.0.0` 形式。
4. 测试库 `alembic_version` 被 conftest 硬编码为 `0001_init`（结构实际是最新 27 表），影响 `/system/db` 在测试环境的版本展示。

### 2.15 测试规模

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
  acceptance/test_stage5_filters.py ~180 行 库存状态与组合筛选（7 项）
  acceptance/test_stats.py        ~250 行 统计口径与粒度（15 项）
  acceptance/test_nutrition_stage7.py ~230 行 营养项目/档案/快照/周期/达标率（11 项）
  acceptance/test_ai_assist.py    ~290 行 AI 闸门/条码/提醒/建议（16 项，阶段 8）
  acceptance/test_recipes.py      ~330 行 菜谱 CRUD/步骤/匹配/合并清单（17 项）
  acceptance/test_backup.py       ~260 行 备份/导出/定时任务/清单增强（13 项，M7）
合计 230 项，全绿
```

---

## 3. 未完成（明确列出，避免误判）

| 项 | 现状 |
| --- | --- |
| 移动端重新签名 | Android debug 包免签名可直接装；iOS 免费 Personal Team 签名 **7 天有效期**，到期需在 Xcode 或 `xcodebuild` 重跑续签 |
| 备份异地副本 | 逻辑备份与 `pg_dump` 都在 NAS 同一块盘，`prune_backups(keep=7)` 保留 7 份；无异地/云副本 |
| 菜谱步骤编辑 UI | 步骤已结构化并展示（含单步时长），但只读，不能在界面上增删改步骤 |
| 定时作业不补跑 | APScheduler 为进程内作业，容器重启重新注册，错过的 03:00/03:10/08:00 窗口不会补跑 |

已完成（此前列在本节的 4 项均已交付）：M9 平台目录、APK 出包、清单一键入库、`PairView.vue` 死文件清理。

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
| K21 | 对账曾需人工触发 | 定时任务未接入时差异可能留存 | 已由 APScheduler 03:00 作业自动修复（M7） | ✅ 已修复 |
| K23 | 批次详情页未内置盘点/报损入口 | 需回到食材详情页操作 | 不影响功能；批次详情已提供「记一笔消耗」与食材档案跳转 | ⚠️ 已知 |
| K22 | 盘点盘盈会改动 `batches.initial_*` 与 `purchase_cost` | 历史「初始量」不再是最初入库值 | 保持 `remaining <= initial` 约束的必要语义；变更记录在 `adjustment` 流水里 | ℹ️ 设计取舍 |

已关闭：K1~K8、K10。

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | `backend/.venv`，pytest 230 项可用 |
| 本机 PostgreSQL | ✅ 16.15 | 库 `freshkeep` 与测试库 `freshkeep_test`；本机 `0004`，测试库建表用 `001_init.sql` |
| 容器三件套 | ✅ | `freshkeep-{db,api,web}` 全 healthy，对外 8080 |
| 容器内迁移版本 | ✅ | `0004_recipe_steps` |
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
cd backend && .venv/bin/python -m pytest          # 期望 232 passed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps                                  # 期望 3 个 healthy
docker compose exec -T db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
psql -d freshkeep -tAc "select version_num from alembic_version"   # 两库应一致
```

---

## 7. 下一步（V1.0.0 发布准备）

功能开发已全部完成（阶段 0~9 + M0~M9、M10）。当前处于**工程化与发布阶段**，8 个阶段依次推进：

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 项目现状审计与备份 | ✅ 完成（§2.17） |
| 2 | GitHub 仓库整理与安全检查 | ✅ 完成 |
| 3 | 文档与部署配置、代码质量规范化 | ✅ 完成 |
| 4 | Docker 镜像构建与打包 | ✅ 完成（GHCR 推送待 PAT） |
| 5 | GitHub Actions CI/CD | ⬜ |
| 3 | 代码质量与测试规范化 | ⬜ |
| 4 | Docker 镜像与 GHCR 发布 | ⬜ |
| 5 | GitHub Actions CI/CD | ⬜ |
| 6 | 版本号与 Release | ⬜ |
| 7 | NAS 固定版本部署与回滚 | ⬜ |
| 8 | 发布验收 | ⬜ |

运维事项（不阻塞发布）：

1. **iOS 签名续签**：免费 Personal Team 7 天有效期，到期重跑 `xcodebuild ... -allowProvisioningUpdates build`。
2. **证书信任**：NAS 用自签证书（SAN 含 `192.168.31.198`），客户端首次访问需信任；公网访问应换 CA 证书。
3. **备份异地**：建议把 `backups/` 同步到另一块卷或云存储。
4. **定时作业补跑**：若需要严格不丢窗口，可改成外部 cron 调用 `POST /tasks/{id}/run`。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-12 15:58 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `8eaf2d5` |
| 工作区 | 111 个未提交改动，未跟踪 7 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0004_recipe_steps`，27 张表 |
| 后端测试 | 232 passed, 3 warnings in 19.09s |
| 前端产物 | 已构建 |
| 文档检查 | 通过 |

最近 5 次提交：

```
8eaf2d5 2026-11-12 docs: 补阶段 2 的 CHANGELOG 条目（安全审计/忽略规则/规范化/NAS 清理）
efce1bd 2026-11-12 chore(repo): V1.0.0 阶段 2 —— 仓库规范化与安全审计
d27dece 2026-11-12 docs: V1.0.0 发布准备 · 阶段 1 现状审计与备份结论
f19dfd2 2026-11-12 feat: M9 收尾 —— iOS 平台工程入库 + 真机签名配置
938a25d 2026-11-11 feat: M9 Android 平台生成 + 清单一键入库
```
<!-- AUTO:STATUS:END -->
