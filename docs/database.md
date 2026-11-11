# 数据库字段设计文档

> 权威 DDL：`database/001_init.sql`（可直接 `psql -f` 执行）。
> 本文与 DDL 不一致时以 DDL 为准，并视为缺陷（见 `AGENTS.md`）。
> ER 图与关系：`docs/er-diagram.md`。

---

## 1. 五条设计不变式

| # | 不变式 | 落地方式 |
| --- | --- | --- |
| I1 | **库存余额 = 初始 + 全部流水之和** | `inventory_transactions` 是唯一写入口；`batches.remaining_*` 只是缓存 |
| I2 | **每笔库存变化都必须能分摊到具体批次** | `transaction_allocations`，且 `UNIQUE(transaction_id, batch_id)` |
| I3 | **历史不可物理删除** | 全表 `ON DELETE RESTRICT`（除从属关系用 CASCADE）；撤销走 `type='reverse'` |
| I4 | **营养数据在消耗时冻结** | `consumption_nutrition` + `basis_snapshot`（jsonb），改档案不影响历史 |
| I5 | **金额与重量一律精确十进制** | `NUMERIC(14,2)` / `NUMERIC(14,3)`，禁止浮点 |

---

## 2. 表清单（26 张）

| # | 表名 | 用途 | 量级 | 来源 |
| --- | --- | --- | --- | --- |
| 1 | `users` | 用户（单行 owner，审计归属） | 1 | PRD |
| 2 | `devices` | 已授权设备与令牌哈希 | 个位数 | **本项目新增** |
| 3 | `pair_codes` | 一次性配对码 | 极少 | **本项目新增** |
| 4 | `file_assets` | 图片/导出/备份文件元数据 | 百~千 | PRD |
| 5 | `categories` | 食材分类（两级） | 十~几十 | PRD |
| 6 | `units` | 计量单位（数量/重量/体积） | 十~几十 | PRD |
| 7 | `storage_locations` | 储存位置 | 个位数 | PRD |
| 8 | `ingredients` | 食材档案（"是什么"） | 百~千 | PRD |
| 9 | `ingredient_barcodes` | 条码 | 百~千 | PRD |
| 10 | `nutrition_definitions` | 营养项目字典 | 十以内 | PRD |
| 11 | `ingredient_nutrition` | 食材营养档案（版本化） | 千 | PRD |
| 12 | `nutrition_targets` | 营养目标 | 十 | PRD |
| 13 | `batches` | 库存批次（"哪一次买的"） | 千~万 | PRD |
| 14 | `inventory_transactions` | 库存流水（唯一真相） | 万 | PRD |
| 15 | `transaction_allocations` | 流水→批次分摊 | 万~十万 | PRD（**核心**） |
| 16 | `consumption_records` | 消耗单头（1:1 流水） | 万 | PRD |
| 17 | `consumption_nutrition` | 消耗营养快照 | 万~十万 | PRD（**核心**） |
| 18 | `shopping_lists` | 采购清单 | 百 | PRD |
| 19 | `shopping_list_items` | 清单项 | 千 | PRD |
| 20 | `recipes` | 菜谱 | 百 | PRD |
| 21 | `recipe_items` | 菜谱所需食材 | 千 | PRD |
| 22 | `notifications` | 提醒排程记录 | 万 | PRD |
| 23 | `app_settings` | 系统设置键值 | 十 | PRD |
| 24 | `audit_logs` | 审计与对账差异 | 万 | PRD |
| 25 | `idempotency_keys` | 写操作幂等 | 千（24h 清理） | **本项目新增** |
| 26 | `recognition_drafts` | AI 识别**待确认**草稿（与库存表零耦合） | 千 | **本项目新增**（阶段 8） |

---

## 3. 核心六表（逐字段）

### 3.1 `batches`（批次）

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | `gen_random_uuid()` | 主键 |
| `ingredient_id` | uuid | 否 | — | → `ingredients` |
| `batch_no` | text | 否 | — | 同食材内唯一（如 `20261108-01`） |
| `purchase_date` | date | 否 | — | 采购日 |
| `production_date` | date | 是 | — | 生产日（可空） |
| `expiry_date` | date | 是 | — | 到期日；空 = 无保质期，FEFO 排最后 |
| `opened_date` | date | 是 | — | 开封日；用于推导开封后保质期（P1） |
| `storage_location_id` | uuid | 是 | — | → `storage_locations` |
| `initial_quantity` / `initial_weight` | numeric(14,3) | 否 | 0 | 入库时的数量/重量 |
| `remaining_quantity` / `remaining_weight` | numeric(14,3) | 否 | 0 | **缓存**，由分配聚合得出 |
| `purchase_cost` | numeric(14,2) | 否 | 0 | 本批总价 |
| `remaining_cost` | numeric(14,2) | 否 | 0 | **缓存**，扣完必须为 0 |
| `status` | text | 否 | `active` | `active` / `depleted` / `void` |
| `note` | text | 否 | `''` | — |
| `created_at` / `updated_at` | timestamptz | 否 | `now()` | `updated_at` 由触发器维护 |

**约束**：`remaining_* <= initial_*`（`ck_batch_remaining_le_initial`）；`remaining_* >= 0`；`expiry_date >= production_date`。
**索引**：`ux_batches_no(ingredient_id, batch_no)`；`ix_batches_fefo(ingredient_id, expiry_date NULLS LAST, purchase_date, id) WHERE status='active'`。

### 3.2 `inventory_transactions`（库存流水）

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | — | 主键 |
| `transaction_no` | text | 否 | — | 业务单号，全局唯一（`TX-purchase-000123`） |
| `type` | text | 否 | — | `purchase` / `consume` / `spoilage` / `adjustment` / `reverse` |
| `ingredient_id` | uuid | 否 | — | → `ingredients` |
| `quantity_delta` | numeric(14,3) | 否 | 0 | 数量维度变化（带符号） |
| `weight_delta` | numeric(14,3) | 否 | 0 | 重量维度变化（带符号） |
| `cost_delta` | numeric(14,2) | 否 | 0 | 成本变化（带符号） |
| `related_object_type` | text | 是 | — | `consumption` / `spoilage` / `adjustment` / `transaction` / `batch` |
| `related_object_id` | uuid | 是 | — | 关联对象 id（撤销时指向原流水） |
| `reason` | text | 否 | `''` | 调整/报损原因 |
| `device_id` | uuid | 是 | — | 操作来源设备 |
| `created_at` | timestamptz | 否 | `now()` | — |

**符号约束**（`ck_tx_sign`）：`purchase` 三个 delta 均 ≥ 0；`consume`/`spoilage` 均 ≤ 0；`adjustment`/`reverse` 不限。

### 3.3 `transaction_allocations`（流水→批次分摊）★

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | — | 主键 |
| `transaction_id` | uuid | 否 | — | → `inventory_transactions`，`ON DELETE CASCADE` |
| `batch_id` | uuid | 否 | — | → `batches`，`ON DELETE RESTRICT` |
| `quantity_delta` | numeric(14,3) | 否 | 0 | 对本批次的数量作用（符号与流水一致） |
| `weight_delta` | numeric(14,3) | 否 | 0 | 对本批次的重量作用 |
| `cost_delta` | numeric(14,2) | 否 | 0 | 对本批次的成本作用 |
| `unit_cost` | numeric(14,4) | 是 | — | **快照**：本次使用的单位成本（元/g），用于审计与复算 |
| `created_at` | timestamptz | 否 | `now()` | — |

**唯一约束** `UNIQUE(transaction_id, batch_id)`：一笔流水对一个批次只有一条分摊。
**索引** `ix_alloc_batch(batch_id)`：对账按批次聚合；`ix_alloc_tx(transaction_id)`：撤销时取全部分摊。

**不变式**（对账任务每日验证）：
```
batches.remaining_weight = Σ transaction_allocations.weight_delta   (按 batch 聚合)
batches.remaining_cost   = Σ transaction_allocations.cost_delta
```
由视图 `v_batch_reconcile` 直接给出三个 `diff_*`，应恒为 0。

### 3.4 `consumption_records`（消耗单头）

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | — | 主键 |
| `consumption_no` | text | 否 | — | 业务单号（`CS-20261108-001`） |
| `ingredient_id` | uuid | 否 | — | → `ingredients` |
| `transaction_id` | uuid | 否 | — | → `inventory_transactions`，**UNIQUE（1:1）** |
| `quantity` / `weight` | numeric(14,3) | 否 | 0 | 本次消耗量（至少一个 > 0） |
| `quantity_unit_id` / `weight_unit_id` | uuid | 是 | — | 展示单位 |
| `cost` | numeric(14,2) | 否 | 0 | 本次成本 = 各分摊之和 |
| `consumed_at` | timestamptz | 否 | — | 业务发生时间（可回溯补录） |
| `note` | text | 否 | `''` | — |
| `status` | text | 否 | `completed` | `completed` / `reversed` |
| `reversed_by_transaction_id` | uuid | 是 | — | 冲销流水；由 CHECK 与 `status` 绑定 |
| `device_id` | uuid | 是 | — | 操作设备 |
| `idempotency_key` | text | 是 | — | 唯一（partial），同一 key 只落一单 |

### 3.5 `consumption_nutrition`（营养快照）★

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | — | 主键 |
| `consumption_id` | uuid | 否 | — | → `consumption_records`，`ON DELETE CASCADE` |
| `nutrition_definition_id` | uuid | 否 | — | → `nutrition_definitions` |
| `actual_value` | numeric(14,4) | 否 | — | 本次摄入量（如 495.0000 kcal） |
| `unit` | text | 否 | — | `kcal` / `g` / `mg`（冗余，防字典改名影响历史展示） |
| `basis_snapshot` | jsonb | 否 | — | 快照依据：`{value, basis_amount, basis_unit, source, version}` |
| `created_at` | timestamptz | 否 | `now()` | — |

**唯一约束** `UNIQUE(consumption_id, nutrition_definition_id)`：一次消耗每个营养项目只有一条。
**为什么必须落表而不是查询时关联**：`ingredient_nutrition` 会随用户修正而变版本；若统计时实时 JOIN，
改一次营养档案会"改写"过去半年的所有统计。快照让历史恒定。

### 3.6 `ingredients`（食材档案）

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | uuid | 否 | — | 主键 |
| `name` | text | 否 | — | 名称 |
| `name_pinyin` / `name_initials` | text | 否 | `''` | 全拼/首字母，写入时由后端（`pypinyin`）生成，供搜索 |
| `category_id` | uuid | 是 | — | → `categories` |
| `image_asset_id` | uuid | 是 | — | → `file_assets` |
| `brand` / `specification` | text | 否 | `''` | 品牌/规格 |
| `default_quantity_unit_id` | uuid | 是 | — | 默认数量单位（个/盒/包） |
| `default_weight_unit_id` | uuid | 是 | — | 默认重量单位（g/斤） |
| `default_unit_weight` | numeric(14,3) | 是 | — | 1 个数量单位 = N 克；**NULL = 禁止自动换算** |
| `nutrition_basis_amount` / `nutrition_basis_unit_id` | — | 是 | — | **仅用于录入预填**，不参与计算（计算基准在 `ingredient_nutrition`） |
| `default_storage_location_id` | uuid | 是 | — | → `storage_locations`；食材的默认存放位置，批次上的同名列可覆盖它（迁移 `0002` 加入） |
| `minimum_quantity` / `minimum_weight` | numeric(14,3) | 否 | 0 | 低库存阈值 |
| `note` | text | 否 | `''` | — |
| `is_active` | boolean | 否 | `true` | 停用而非删除 |

**注意**：本表**不含任何库存数字**。库存全部来自 `v_inventory`（批次聚合）。

---

## 4. 其余 19 表的要点（字段详见 DDL）

| 表 | 关键字段与约束 |
| --- | --- |
| `users` | `username` 唯一；`password_hash` 可空（当前恒 NULL，配对码方案） |
| `devices` | `token_hash` 唯一；`platform ∈ (web, ios, android)`；`revoked_at` 非空即失效 |
| `pair_codes` | `code_hash` 唯一；`expires_at` + `used_at` 控制一次性 |
| `file_assets` | `checksum` 唯一（同图不重复存）；`category ∈ (image, export, backup, temp)` |
| `categories` | 自引用 `parent_id`；同级不重名由两条 partial unique index 保证 |
| `units` | `dimension ∈ (quantity, weight, volume)`；**跨 dimension 禁止换算** |
| `storage_locations` | `name` 唯一 |
| `ingredient_barcodes` | `barcode` 全局唯一；`ON DELETE CASCADE`（食材删则条码删） |
| `nutrition_definitions` | `code` 唯一（calories/protein/fat/carbs/fiber/sodium） |
| `ingredient_nutrition` | partial unique `(ingredient_id, nutrition_definition_id) WHERE is_current` |
| `nutrition_targets` | `UNIQUE(nutrition_definition_id, period, effective_from)`，按生效日留痕 |
| `shopping_lists` | `status ∈ (open, completed, archived)` |
| `shopping_list_items` | `ingredient_id` 可空 + `free_text_name`，二者至少一个（未建档食材也能记） |
| `recipes` | `servings > 0`；`image_asset_id` 可空 |
| `recipe_items` | `quantity` 或 `weight` 至少一个非空 |
| `notifications` | `status ∈ (pending, scheduled, sent, skipped)`；部分索引只查待发 |
| `app_settings` | `key` 主键，`value_json` jsonb |
| `audit_logs` | `before_json`/`after_json`；对账差异用 `action='reconcile_mismatch'` |
| `idempotency_keys` | `key` 主键；`request_hash` 比对 body；24h 清理 |

---

## 5. 索引清单与理由

| 索引 | 服务的查询 | 为什么需要 |
| --- | --- | --- |
| `ix_batches_fefo` | FEFO 取批次（按到期日升序） | 每次消耗都要走它，是最高频查询；`NULLS LAST` 让无保质期批次排最后 |
| `ix_batches_expiring` | 临期扫描 | 部分索引只覆盖有库存的活跃批次，体积小 |
| `ux_batches_no` | 批次号唯一 | 防重复录入同一批 |
| `ix_tx_ingredient_time` | 食材详情页的流水列表 | 按食材 + 时间倒序 |
| `ix_tx_related` | 撤销时找原流水 / 追溯 | 关联对象反查 |
| `ix_alloc_batch` | 对账、批次详情"这笔从哪来" | 按批次聚合分摊 |
| `ix_cons_time` | 记录页分页 | 按时间倒序 |
| `ix_cons_nutrition_def` | 营养统计按项目聚合 | 避免全表扫 |
| `ix_ingredients_name_trgm` | 中文模糊搜索 | `pg_trgm` GIN，支持 `ILIKE '%牛奶%'` |
| `ix_ingredients_py_trgm` | 拼音/首字母检索 | 同上，`nn`/`niumai` 都能命中 |
| `ux_ing_nutrition_current` | 保证每项目只有一条当前值 | 数据正确性 |
| `ux_cons_idem` | 幂等键唯一 | 防重复消耗单 |

---

## 6. 视图

| 视图 | 用途 | 使用方 |
| --- | --- | --- |
| `v_inventory` | 食材级库存汇总（数量/重量/成本/批次数量/最近到期/是否低库存） | 首页、库存页、采购建议 |
| `v_batch_reconcile` | 批次缓存余额 vs 分配聚合的三个差异 | 每日对账任务 |

> 所有页面只读视图，不在业务代码里重复写聚合 SQL——避免"三个页面三种算法"。

---

## 7. 取值字典

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `inventory_transactions.type` | `purchase` | 采购入库（正） |
| | `consume` | 消耗出库（负） |
| | `spoilage` | 报损（负） |
| | `adjustment` | 盘点调整（可正可负，`reason` 必填） |
| | `reverse` | 冲销（对原流水取反） |
| `units.dimension` | `quantity` | 个数类（个、盒、包） |
| | `weight` | 重量类（g、kg、斤） |
| | `volume` | 体积类（ml、L） |
| `ingredient_nutrition.source` | `manual` / `packaging_label` / `database` | 手动 / 包装表识别 / 外部库 |
| `notifications.type` | `expiring` / `expired` / `low_stock` / `backup` | 提醒类别 |

---

## 8. 与 PRD 的差异（3 张新表 + 2 处字段调整）

| 项 | PRD | 本设计 | 原因 |
| --- | --- | --- | --- |
| `devices` | 无 | 新增 | PRD 的 `users` 只有密码哈希，没有设备令牌概念；配对码方案必须承载"谁被授权" |
| `pair_codes` | 无 | 新增 | 一次性码只存哈希 |
| `idempotency_keys` | PRD §5.5 要求幂等，未给载体 | 新增 | 幂等必须落表才能跨请求生效 |
| `users.password_hash` | 必填密码 | 保留字段、恒为 NULL | 认证走配对码；保留字段使将来加密码不需迁移 |
| `consumption_nutrition` | 有表无细节 | 增加 `basis_snapshot jsonb` | 让"当时用的什么基准"可审计，而不只是结果值 |

---

## 9. 评审结论（逐条对照阶段 0 验收标准）

| 验收标准 | 结论 | 证据 |
| --- | --- | --- |
| 所有核心数据表都有明确用途 | ✅ | §2 的 25 行"用途"列，无占位表 |
| 表之间外键关系合理 | ✅ | 全部写出 `REFERENCES` 与 `ON DELETE` 策略；仅从属关系用 CASCADE（`barcodes`、`consumption_nutrition`、`shopping_list_items`、`recipe_items`） |
| 库存流水与批次分配关系明确 | ✅ | `transaction_allocations` 带 `UNIQUE(transaction_id, batch_id)`，并有对账视图 `v_batch_reconcile` 验证 I1 |
| 营养快照表已设计 | ✅ | `consumption_nutrition` 含 `actual_value` + `basis_snapshot`，唯一约束防重复项 |
| 不再存在需猜测的核心业务规则 | ✅ | 符号、精度、状态机、FEFO 排序、尾差结清、换算禁则均已写死（见 §3、§7 与 `final-plan.md` §9） |

---

## 10. 已知的、明确留到后续的表结构扩展点

| 扩展点 | 触发条件 | 预留方式 |
| --- | --- | --- |
| 批次"开封后保质期" | P1 做临期提醒时 | `batches.opened_date` 已建；只需加 `ingredients.opened_shelf_life_days` |
| 采购清单"已忽略项" | P2 | `shopping_list_items` 加 `dismissed_at` |
| 多币种 | 若需要 | `batches` 加 `currency`；当前默认单一货币（PRD §12 已列入待明确） |
| 营养项目扩展（如糖、钙） | 需要时 | 只插 `nutrition_definitions` 一行，不改表结构 |

---

## 迁移历史

| 版本 | 内容 | 是否改表 |
| --- | --- | --- |
| `0001_init` | 25 表 + 2 视图 + 索引/约束/触发器 | 建表 |
| `0002_ingredient_storage` | `ingredients` 增加 `default_storage_location_id`（FK → `storage_locations`，`ON DELETE SET NULL`）+ 部分索引 `ix_ingredients_location` | 加列 + 加索引 |
| `0003_recognition_drafts` | 新增 `recognition_drafts`（AI 识别草稿：`draft`/`warnings` jsonb、`status` 三态、`confirmed_entity_type/id`）+ 索引 `ix_recognition_status` | 建表 + 加索引 |

> `0002` 用 `ADD COLUMN IF NOT EXISTS`，对已含该列的新库为空操作，可重复执行。
>
> `0003` 用 `CREATE TABLE IF NOT EXISTS`，新库（`001_init.sql` 已含该表）执行时为空操作。
> 该表存在的意义：**AI 结果只能落这里**，人工确认后才由确认接口调用建档/入库服务，
> 保证「AI 不可能直接改库存」。
