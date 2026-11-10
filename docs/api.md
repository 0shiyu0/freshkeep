# API 接口规范（初稿 V1）

> 基础路径 `/api/v1`；实现框架 FastAPI（自动产出 OpenAPI，`/docs` 可直接调试）。
> 本文是**契约初稿**，进入 M1 后由 FastAPI 的 Pydantic 模型反向约束，二者不一致视为缺陷。

---

## 1. 通用约定

### 1.1 认证

| 客户端 | 凭据 | 传递方式 |
| --- | --- | --- |
| Web（同源） | 设备令牌 | `Cookie: fk_sid=<token>`（HttpOnly / SameSite=Lax） |
| App（跨源） | 设备令牌 | `Authorization: Bearer <token>` |

服务端按 `Bearer → Cookie` 顺序取令牌，两者都映射到 `devices.id`。
除 `GET /ping`、`GET /health`、`POST /auth/pair` 外，全部接口要求已认证。

### 1.2 统一响应

```json
// 成功
{ "success": true, "data": { }, "message": "操作成功", "request_id": "0f3a…" }

// 失败
{ "success": false, "error": { "code": "INSUFFICIENT_STOCK", "message": "批次可用量不足，还差 120g" },
  "request_id": "0f3a…" }
```

`request_id` 由服务端生成并写日志，便于按 id 反查。

### 1.3 数值与时间

| 类型 | 传输格式 | 说明 |
| --- | --- | --- |
| 金额（元） | **字符串** `"10.80"` | 绝不返回 JS number，避免浮点误差；前端按字符串展示 |
| 重量/数量 | **字符串** `"300.000"` | 同上 |
| 营养值 | **字符串** `"495.0000"` | 同上 |
| 时间戳 | ISO 8601 带时区 `"2026-11-08T14:30:00+08:00"` | 数据库存 UTC，接口按 `Asia/Shanghai` 输出 |
| 日期 | `"2026-11-10"` | 到期日/采购日等纯日期字段 |

服务端内部一律 `Decimal`，Pydantic 用 `Decimal` 并在序列化时转字符串（`model_config` 配 `json_encoders`）。

### 1.4 幂等

所有"会产生库存变化"的 POST 都接受 `Idempotency-Key` 头（建议 UUID）：

- 同 key + 同 body → 返回**首次的响应**（HTTP 200），不重复执行；
- 同 key + 不同 body → `409 DUPLICATE_REQUEST`；
- 无该头 → 不做幂等保护（仅供调试）。
- 记录保留 24 小时。

### 1.5 分页与排序

`?page=1&page_size=20&sort_by=created_at&sort_order=desc`，返回：

```json
{ "items": [ ], "total": 128, "page": 1, "page_size": 20 }
```

`page_size` 上限 100；`sort_by` 白名单校验，非法字段返回 `VALIDATION_ERROR`。

### 1.6 错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 参数不合法（字段级错误在 `error.details`） |
| 401 | `UNAUTHORIZED` | 未认证或令牌失效 |
| 403 | `FORBIDDEN` | 网段不在允许范围（`ALLOW_CIDR`） |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `DUPLICATE_REQUEST` | 幂等键冲突且 body 不同 |
| 409 | `CONFLICT` | 状态冲突（如重复撤销） |
| 422 | `INSUFFICIENT_STOCK` | 库存不足（`error.details.shortage` 给出缺口） |
| 422 | `UNIT_NOT_CONVERTIBLE` | 数量↔重量无换算关系 |
| 422 | `INCONSISTENT_MEASURE` | 数量与重量按换算关系不自洽 |
| 429 | `RATE_LIMITED` | 配对码尝试过多 |
| 503 | `DB_BUSY` | 数据库忙（可重试） |

---

## 2. 接口清单

### 2.1 认证与设备

| 方法 | 路径 | 关键请求 | 说明 |
| --- | --- | --- | --- |
| GET | `/ping` | — | `{name, version, initialized, needs_pair, server_time}`，客户端探测用 |
| GET | `/health` | — | 容器健康检查，含 db 连通性 |
| POST | `/auth/pair` | `code, device_name, platform` | Web 下发 Cookie / App 返回 `{token, device}` |
| GET | `/auth/me` | — | 当前设备与用户信息 |
| GET | `/auth/devices` | — | 已授权设备列表（含最后活跃时间） |
| DELETE | `/auth/devices/{id}` | — | 吊销设备（"退出登录"与"手机丢了"共用） |

### 2.2 档案

| 方法 | 路径 | 关键请求 | 说明 |
| --- | --- | --- | --- |
| GET/POST | `/categories` | `name, parent_id, sort_order` | 列表含子节点计数 |
| PUT/DELETE | `/categories/{id}` | 同上 | 有食材引用时删除返回 `CONFLICT` |
| PUT | `/categories/sort` | `[{id, sort_order}]` | 拖拽排序 |
| GET/POST | `/units` | `name, symbol, dimension, precision` | 单位字典 |
| PUT/DELETE | `/units/{id}` | — | 被引用时拒绝删除 |
| GET/POST | `/storage-locations` | `name, description, sort_order` | 储存位置 |
| GET | `/ingredients` | `q, category_id, is_active, is_low_stock, location_id, page…` | 列表；`q` 支持中文/拼音/首字母 |
| POST | `/ingredients` | 见 §3.1 | 建档 |
| GET/PUT/DELETE | `/ingredients/{id}` | — | 删除为软删（`is_active=false`），有批次时返回 `CONFLICT` |
| GET | `/ingredients/{id}/batches` | `include_empty=false` | 批次列表（按 FEFO 顺序） |
| GET | `/ingredients/{id}/transactions` | `page…` | 该食材全部流水 |
| GET/PUT | `/ingredients/{id}/nutrition` | 见 §3.2 | 读取当前营养档案 / 写入新版本 |
| GET | `/barcodes/{code}` | — | 扫码定位食材 |
| POST/DELETE | `/barcodes[/{id}]` | `ingredient_id, barcode, barcode_type` | 绑定/解绑条码 |

### 2.3 批次与入库

| 方法 | 路径 | 关键请求 | 说明 |
| --- | --- | --- | --- |
| POST | `/batches` | 见 §3.3 | 新建批次 = 一次采购入库，同一事务写 `purchase` 流水 + 分配 |
| GET | `/batches` | `q, ingredient_id, location_id, status, page…` | 批次列表（`q` 支持食材中文/拼音/首字母） |
| GET/PUT | `/batches/{id}` | `expiry_date, storage_location_id, opened_date, note` | 只允许改元数据，**不允许改数量**（改数量必须走盘点） |
| GET | `/batches/expiring` | `days=7` | 临期批次（按剩余天数升序） |
| GET | `/batches/expired` | — | 已过期且仍有库存 |

### 2.4 消耗

| 方法 | 路径 | 关键请求 | 说明 |
| --- | --- | --- | --- |
| POST | `/consumptions` | 见 §3.4 | 单食材消耗，FEFO 自动分配 |
| POST | `/consumptions/batch` | `[{ingredient_id, weight, quantity}], consumed_at` | 批量消耗；**整批成功或整批回滚** |
| GET | `/consumptions` | `ingredient_id, from, to, status, page…` | 消耗记录分页 |
| GET | `/consumptions/{id}` | — | 详情含批次分配明细与营养快照 |
| POST | `/consumptions/{id}/reverse` | `reason` | 冲销：新增 `reverse` 流水 + 反向分配，原记录置 `reversed` |

### 2.5 库存

| 方法 | 路径 | 关键请求 | 说明 |
| --- | --- | --- | --- |
| GET | `/inventory` | `category_id, is_low_stock, location_id, q, page…` | 读 `v_inventory` |
| GET | `/inventory/summary` | `as_of?` | 总数量/总重量/总成本/食材数/临期数 |
| GET | `/inventory/transactions` | `type, ingredient_id, batch_id, from, to, page…` | 全部流水；`batch_id` 经分配表反查 |
| POST | `/inventory/adjustments` | `ingredient_id, batch_id?, actual_weight, actual_quantity, reason` | 盘点调整：**提交实际值**，服务端反算 delta |
| POST | `/inventory/stocktake` | `[{batch_id, actual_weight, actual_quantity}]` | 批量盘点，整批事务 |
| POST | `/inventory/spoilage` | `ingredient_id, weight, quantity, reason` | 报损（走 `spoilage` 流水） |

### 2.6 首页、统计与营养

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/dashboard/summary` | 库存总价值、周期采购额、周期消耗额、消耗比例 |
| GET | `/dashboard/recent-batches` | 最近 4 条入库 |
| GET | `/dashboard/alerts` | 临期/过期/低库存聚合（App 据此排本地通知） |
| GET | `/dashboard/nutrition` | 今日/近三天/本周营养汇总（标注"按库存消耗量估算"） |
| GET | `/dashboard/quick-stats` | 首页迷你卡片 |
| GET | `/statistics/finance` | `from,to,group_by`：采购金额、消耗成本、报损金额、库存价值 |
| GET | `/statistics/categories` | 分类维度的金额/数量分布 |
| GET | `/statistics/consumption` | 消耗排行与趋势 |
| GET | `/statistics/nutrition` | 营养趋势（区分"无记录"与"0 摄入"） |
| GET | `/nutrition/definitions` | 营养项目字典 |
| GET/PUT | `/nutrition/targets` | 目标值（按生效日留痕） |
| GET | `/nutrition/daily` | `from,to`：每日摄入与达标率 |

### 2.7 菜谱、采购清单、文件、导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/recipes`；GET/PUT/DELETE `/recipes/{id}` | 菜谱 CRUD |
| GET | `/recipes/{id}/availability` | 库存可满足量 / 缺少量 |
| POST | `/recipes/{id}/shopping-list` | 按缺口生成采购清单（多菜谱先合并再扣库存） |
| GET/POST | `/shopping-lists`；GET/PUT `/shopping-lists/{id}` | 清单 CRUD |
| POST | `/shopping-lists/{id}/items`；PUT/DELETE `/shopping-list-items/{id}` | 清单项 |
| POST | `/shopping-list-items/{id}/complete` | 勾选完成（可一键转补货） |
| POST | `/files/upload` | `multipart`，校验 MIME/大小/文件名，返回 `file_asset` |
| GET/DELETE | `/files/{id}` | 元数据 / 删除 |
| POST | `/exports` | `type=consumptions\|inventory\|transactions, format=csv\|json` |
| GET | `/exports/{id}`；GET `/exports/{id}/download` | 导出任务状态 / 下载 |
| POST | `/backups`；GET `/backups`；POST `/backups/{id}/restore` | 备份与恢复（P1） |
| POST | `/ai/recognize-image`；`/ai/recognize-nutrition` | P2，返回**待确认草稿**，不直接落库 |

---

## 3. 关键接口的请求/响应样例

### 3.1 `POST /ingredients`（建档）

```json
// 请求
{ "name": "鸡胸肉", "category_id": "…", "brand": "圣农", "specification": "500g/袋",
  "default_quantity_unit_id": "…", "default_weight_unit_id": "…",
  "default_unit_weight": "500", "minimum_weight": "200",
  "nutrition": [
    { "code": "calories", "value": "165", "basis_amount": "100", "basis_unit": "g" },
    { "code": "protein",  "value": "31",  "basis_amount": "100", "basis_unit": "g" }
  ] }
```

响应 `201`：返回食材（含 `id`、由后端生成的 `name_pinyin`/`name_initials`）。

### 3.2 `PUT /ingredients/{id}/nutrition`（改营养档案）

```json
// 请求：整体替换"当前版本"
{ "items": [ { "code": "calories", "value": "170", "basis_amount": "100", "basis_unit": "g" } ] }
```
服务端行为：旧行 `is_current=false`、插入新行 `version+1`、`is_current=true`，**同一事务**。
历史消耗快照不受影响。

### 3.3 `POST /batches`（入库）

```json
// 请求
{ "ingredient_id": "…", "purchase_date": "2026-11-08", "production_date": "2026-11-05",
  "expiry_date": "2026-11-15", "opened_date": "2026-11-08",
  "storage_location_id": "…", "quantity": "2", "weight": "500", "purchase_cost": "18.00",
  "quantity_unit_id": "…", "weight_unit_id": "…", "note": "" }
```

```json
// 响应 201
{ "success": true, "data": {
    "batch": { "id": "…", "batch_no": "20261108-01",
               "initial_weight": "500.000", "remaining_weight": "500.000",
               "purchase_cost": "18.00", "remaining_cost": "18.00", "status": "active" },
    "transaction": { "id": "…", "type": "purchase", "weight_delta": "500.000", "cost_delta": "18.00" }
  }, "message": "入库成功", "request_id": "…" }
```

> 入库也写 `inventory_transactions` + `transaction_allocations`（分配给自己这条批次），
> 保证"任何库存变化都有流水"这一不变式没有例外。

### 3.4 `POST /consumptions`（消耗，最核心）

```json
// 请求（头：Idempotency-Key: 8f2c…）
{ "ingredient_id": "…", "weight": "300", "consumed_at": "2026-11-08T12:30:00+08:00",
  "note": "做沙拉", "batch_ids": null }
```

`batch_ids` 为 `null` 表示按 FEFO 自动分配；显式传数组表示手动指定（仍校验可用量）。

```json
// 响应 201
{ "success": true, "data": {
    "consumption": { "id": "…", "consumption_no": "CS-20261108-001",
                     "weight": "300.000", "cost": "10.80", "status": "completed" },
    "allocations": [
      { "batch_id": "…", "batch_no": "B1", "weight_delta": "-300.000",
        "cost_delta": "-10.80", "unit_cost": "0.0360",
        "batch_remaining_weight": "200.000", "batch_remaining_cost": "7.20" }
    ],
    "nutrition": [ { "code": "calories", "actual_value": "495.0000", "unit": "kcal" } ]
  }, "message": "已记录消耗", "request_id": "…" }
```

**失败样例**（库存不足）：

```json
{ "success": false,
  "error": { "code": "INSUFFICIENT_STOCK", "message": "可用量不足，还差 120g",
             "details": { "required": "300.000", "available": "180.000", "shortage": "120.000" } },
  "request_id": "…" }
```
此时**不产生任何流水**（事务整体回滚）。

### 3.5 `POST /inventory/adjustments`（盘点）

```json
// 请求：提交"实际值"，不是差值
{ "ingredient_id": "…", "batch_id": "…", "actual_weight": "180", "reason": "盘点差异" }
```
服务端计算 `delta = 实际 − 当前`，写 `adjustment` 流水；若明细到批次则同时写分配。

### 3.6 `GET /dashboard/summary?from=2026-11-01&to=2026-11-08`

```json
{ "success": true, "data": {
    "inventory_value": "1284.50",
    "purchase_amount": "320.00",
    "consumption_cost": "186.30",
    "consumption_ratio": "0.5822",
    "ingredient_count": 42, "expiring_count": 3, "low_stock_count": 1
  }, "request_id": "…" }
```

---

## 4. 与 PRD 的差异

| 项 | PRD | 本规范 | 原因 |
| --- | --- | --- | --- |
| 登录 | `/auth/login`、`/auth/change-password` | `/auth/pair`、`/auth/devices` | 认证走配对码（见 `final-plan.md` §2） |
| 单位/位置接口 | 未列 | 已补 `/units`、`/storage-locations` | PRD 有表无接口，缺了前端无法维护字典 |
| 数值类型 | 未规定 | 金额/重量/营养一律**字符串**传输 | 避免 JS 浮点误差 |
| 批量消耗 | `POST /consumptions/batch` | 保留，明确"整批事务" | PRD §5.5 要求 |

---

## 5. 交付节奏

| 阶段 | 覆盖 |
| --- | --- |
| M1 | `/ping`、`/health`、`/auth/*` |
| M2 | 档案域全部（分类/单位/位置/食材/条码/文件） |
| M3 | 批次域 + 入库 |
| M4 | 消耗域 + 撤销（核心） |
| M5 | 库存域（含盘点/报损/流水） |
| M6 | 首页 + 统计 + 营养 |
| M7 | 导出/备份 |
| P1/P2 | 扫码、AI 识别、菜谱、采购清单 |

每个接口完成时补齐：OpenAPI schema、pytest 用例（正常 + 至少一个失败分支）、示例请求写进本文档。
