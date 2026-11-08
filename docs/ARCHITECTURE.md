# 系统架构与设计

> 本文是**架构、数据库、API 三合一的入口文档**。目标：上下文清空后，只读本文即可恢复对系统的完整理解。
> 字段级细节在 `docs/database.md`，接口细节在 `docs/api.md`，决策溯源在 `docs/final-plan.md`。

---

## 1. 系统上下文

```
 iPhone / iPad（原生 App）        安卓（原生 App）          电脑浏览器
        │                              │                       │
        └──────────── 局域网 or 异地组网（Tailscale/ZeroTier）─┘
                              │
                   ┌──────────▼────────────┐
                   │  NAS · Docker Compose  │
                   │  ┌──────────────────┐  │
                   │  │ web 容器（nginx） │  │  托管 dist + 反代 /api
                   │  │  :8080 → :80     │  │
                   │  └────────┬─────────┘  │
                   │  ┌────────▼─────────┐  │
                   │  │ api 容器          │  │  FastAPI（uvicorn :8000）
                   │  │  :8000（不对外）  │  │  日志 → storage/logs
                   │  └────────┬─────────┘  │
                   │  ┌────────▼─────────┐  │
                   │  │ db 容器           │  │  PostgreSQL 16
                   │  │  :5432（不对外）  │  │  数据 → ./pgdata
                   │  └──────────────────┘  │
                   └───────────────────────┘
```

**三个刻意选择**：

| 选择 | 理由 | 代价 |
| --- | --- | --- |
| 三个容器（web / api / db），前端由 nginx 托管并反代 /api | 前端可独立构建与缓存；nginx 处理 gzip、静态缓存、SPA 回退更稳 | 多一个容器；api 端口不再对外 |
| 不做 PWA，提醒由 App 本地通知承载 | Service Worker 与 Notification 都要安全上下文（HTTPS），内网 HTTP 下不可用 | 浏览器端没有系统通知 |
| 不做公网暴露 | 无攻击面、无证书运维 | 外网依赖异地组网 |

---

## 2. 技术栈

| 层 | 组件 | 版本 | 作用 |
| --- | --- | --- | --- |
| 后端 | Python | 3.12+ | 运行时 |
| | FastAPI | 0.162 | 路由、依赖注入、OpenAPI |
| | SQLAlchemy | 2.1 | ORM、事务、行锁（同步模式） |
| | Pydantic | 2.14 | 请求/响应校验、双计量校验 |
| | Alembic | 1.20 | 迁移版本登记（DDL 不在这里写） |
| | psycopg | 3.3 | PostgreSQL 驱动（binary 包，无需编译器） |
| | APScheduler | 3.11 | 临期扫描、对账、备份 |
| 数据库 | PostgreSQL | 16 | 主存储，`NUMERIC` 精确十进制 |
| 前端 | Vue | 3.5 | SPA |
| | Vite | 8.3 | 构建（产物同时供 Web 与 App） |
| | Pinia | 4.1 | 状态 |
| | Naive UI / ECharts | 2.45 / 6.1 | 组件库 / 图表 |
| 移动壳 | Capacitor | 8.6 | APK / IPA 打包 |
| 部署 | Docker Compose v2 | — | NAS 上运行 |

**版本锁定原则**：所有版本号在 `backend/requirements.txt` 与 `frontend/package.json` 里钉死，升级主版本必须走评审。

---

## 3. 运行时结构

### 3.1 目录与职责

```
backend/app/
  main.py          FastAPI 装配：中间件、异常处理、路由挂载、静态托管
  core/            config（环境变量）、errors（统一错误）
  db/              session（引擎、`get_db` 依赖、`session_scope`）
  models/          25 张表的 ORM 定义（M1 起）
  schemas/         Pydantic 模型（含双计量 validator）
  services/        业务逻辑：fefo / cost / nutrition / inventory / reconcile
  api/v1/          路由层，只做参数校验与响应包装
  tasks/           APScheduler 任务
  cli.py           命令行：pair / devices / revoke
```

**分层铁律**：`api/v1` → `services` → `models`。路由器里不写业务逻辑。

### 3.2 请求管线（顺序固定）

```
ALLOW_CIDR（网段白名单）→ 静态资源直出 → /api：body 解析 → 认证 → 限流 → Origin 校验（仅写操作）→ 路由
```

---

## 4. 认证与凭据

**唯一入口是配对码**，没有密码（决策见 `docs/final-plan.md` §2）。

```
① NAS 上执行 docker compose exec api python -m app.cli pair
   → 6 位码（去掉 0/O/1/I/L），10 分钟有效，一次性，只存 SHA-256
② 客户端 POST /api/v1/auth/pair {code, device_name, platform}
   → 生成 32 字节令牌（只存 SHA-256），写 devices 表
   → Web：Set-Cookie fk_sid（HttpOnly, SameSite=Lax；HTTP 下无 Secure）
   → App：响应体返回 token，存 iOS Keychain / Android Keystore
③ 之后：Web 自动带 Cookie（同源）；App 带 Authorization: Bearer（跨源）
   服务端按 Bearer → Cookie 顺序取令牌，都映射到 devices.id
④ 令牌不过期；吊销 = devices.revoked_at，即时生效
```

**为什么 App 不能用 Cookie**：App 的 origin 是 `capacitor://localhost` / `http://localhost`，向 `http://NAS_IP` 请求属跨站；
跨站带 Cookie 必须 `SameSite=None; Secure`，而 HTTP 下带 `Secure` 会被直接丢弃——协议层就断了。

**CORS**：只放行 `capacitor://localhost`、`http://localhost`、`http://localhost:5173`，`allow_credentials=False`（走 Bearer）。

---

## 5. 数据模型

### 5.1 五条不变式（违反即为缺陷）

| # | 不变式 | 保障方式 |
| --- | --- | --- |
| I1 | 库存余额 = 初始 + 全部流水之和 | `inventory_transactions` 是唯一写入口 |
| I2 | 每笔库存变化都能分摊到具体批次 | `transaction_allocations`，`UNIQUE(transaction_id, batch_id)` |
| I3 | 历史不可物理删除 | 全表 `ON DELETE RESTRICT`；撤销走 `type='reverse'` |
| I4 | 营养在消耗时冻结 | `consumption_nutrition` + `basis_snapshot` |
| I5 | 金额/重量精确十进制 | `NUMERIC(14,2)` / `(14,3)` / `(14,4)`，禁止 float |

### 5.2 25 张表

| 分组 | 表 |
| --- | --- |
| 账号与文件 | `users` `devices` `pair_codes` `file_assets` |
| 基础档案 | `categories` `units` `storage_locations` `ingredients` `ingredient_barcodes` `nutrition_definitions` `ingredient_nutrition` `nutrition_targets` |
| 库存核心 | `batches` `inventory_transactions` `transaction_allocations` `consumption_records` `consumption_nutrition` |
| 采购与菜谱 | `shopping_lists` `shopping_list_items` `recipes` `recipe_items` |
| 系统 | `notifications` `app_settings` `audit_logs` `idempotency_keys` |

**两张关键表**（PRD 明确要求，不可简化）：

- **`transaction_allocations`**：一笔流水对某批次的作用量。没有它就无法回答"这 300g 从哪个批次扣的"，
  撤销、成本分摊、对账全部失去依据。`unit_cost` 是当时的单位成本快照。
- **`consumption_nutrition`**：消耗时冻结的营养值 + `basis_snapshot`（当时的 value/basis/source/version）。
  若改成统计时 JOIN 当前档案，用户改一次营养值就会"改写"历史所有统计。

### 5.3 视图

| 视图 | 用途 |
| --- | --- |
| `v_inventory` | 食材级汇总：数量/重量/成本/批次数量/最近到期/是否低库存。首页、库存页、采购建议统一只读它 |
| `v_batch_reconcile` | 批次缓存余额 vs 分配聚合的三个差异，应恒为 0 |

### 5.4 两个状态机

```
batches.status:            active → depleted（余额归零）/ void（录错作废）
consumption_records.status: completed → reversed（新增 reverse 流水，原记录保留）
```

DDL 与索引见 `database/001_init.sql`；字段级说明见 `docs/database.md`；ER 图见 `docs/er-diagram.md`。

---

## 6. API 规范

### 6.1 约定

| 项 | 规则 |
| --- | --- |
| 基础路径 | `/api/v1` |
| 响应包 | `{success, data, message, request_id}` / `{success:false, error:{code,message,details}, request_id}` |
| 数值 | **金额/重量/营养一律字符串**（`"10.80"`），避免前端浮点误差 |
| 时间 | 时间戳 ISO 8601 带时区；纯日期 `YYYY-MM-DD` |
| 分页 | `page/page_size/sort_by/sort_order`，`sort_by` 白名单校验 |
| 幂等 | 写操作支持 `Idempotency-Key`：同 key 同 body 返回原响应；同 key 不同 body → 409 |
| 错误码 | `VALIDATION_ERROR` `UNAUTHORIZED` `FORBIDDEN` `NOT_FOUND` `DUPLICATE_REQUEST` `CONFLICT` `INSUFFICIENT_STOCK` `UNIT_NOT_CONVERTIBLE` `INCONSISTENT_MEASURE` `RATE_LIMITED` |

### 6.2 端点总表

| 模块 | 端点 |
| --- | --- |
| 系统 | `GET /ping`、`GET /health` |
| 认证 | `POST /auth/pair`、`GET /auth/me`、`GET /auth/devices`、`DELETE /auth/devices/{id}` |
| 档案 | `GET/POST /categories`、`PUT/DELETE /categories/{id}`、`PUT /categories/sort`、`GET/POST /units`、`GET/POST /storage-locations`、`GET/POST /ingredients`、`GET/PUT/DELETE /ingredients/{id}`、`GET/PUT /ingredients/{id}/nutrition`、`GET /ingredients/{id}/batches`、`GET/POST/DELETE /barcodes` |
| 批次 | `POST /batches`、`GET /batches`、`GET/PUT /batches/{id}`、`GET /batches/expiring`、`GET /batches/expired` |
| 消耗 | `POST /consumptions`、`POST /consumptions/batch`、`GET /consumptions`、`GET /consumptions/{id}`、`POST /consumptions/{id}/reverse` |
| 库存 | `GET /inventory`、`GET /inventory/summary`、`GET /inventory/transactions`、`POST /inventory/adjustments`、`POST /inventory/stocktake`、`POST /inventory/spoilage` |
| 首页/统计/营养 | `GET /dashboard/{summary,recent-batches,alerts,nutrition,quick-stats}`、`GET /statistics/{finance,categories,consumption,nutrition}`、`GET /nutrition/{definitions,daily}`、`GET/PUT /nutrition/targets` |
| 菜谱/清单/文件 | `/recipes`、`/recipes/{id}/availability`、`/shopping-lists`、`/shopping-list-items/{id}/complete`、`POST /files/upload`、`/exports`、`/backups` |

请求/响应样例与字段级说明见 `docs/api.md`。

---

## 7. 四个核心算法

### 7.1 FEFO 分配

```python
batches = select(Batch).where(
    Batch.ingredient_id == iid, Batch.status == 'active', Batch.remaining_weight > 0
).order_by(Batch.expiry_date.asc().nulls_last(),
           Batch.purchase_date.asc(), Batch.id.asc()
).with_for_update()          # 行级锁，防并发超卖

left = need
for b in batches:
    if left <= 0: break
    take = min(b.remaining_weight, left)
    cost = b.remaining_cost if take == b.remaining_weight \
           else (take * b.remaining_cost / b.remaining_weight).quantize(Q2)
    left -= take
if left > 0: raise InsufficientStock()
```

三个必须：过滤 `remaining_weight > 0`（否则除零）、全程 `Decimal`、锁顺序固定按 `expiry_date`（防死锁）。

### 7.2 尾差结清

`take == remaining_weight` 时成本直接取 `remaining_cost`，并把该批次剩余成本置 0。
否则会出现"库存归零仍残留 0.01 元"。

### 7.3 双计量

```
两者都传：无 unit_weight → 不一致即 422 UNIT_NOT_CONVERTIBLE；有 → |weight − qty×unit_weight| > 0.001 即 422
只传一个：无 unit_weight → 另一维度 delta 记 0；有 → 按换算补齐并标记 derived
```

### 7.4 对账（每日 03:00）

```sql
SELECT * FROM v_batch_reconcile WHERE diff_weight <> 0 OR diff_cost <> 0;
```
非空 → 写 `audit_logs(action='reconcile_mismatch')` 并修正缓存。差异为 0 是系统健康的判据。

---

## 8. 跨端与构建

```
frontend/dist  ←── npm run build
     │
     ├─→ 后端 StaticFiles 托管（Web，同源，Cookie）
     └─→ Capacitor webDir（App，跨源，Bearer）
```

**一份前端产物、两处消费**，不存在第二套 UI 代码。

Capacitor 三项必须配置（漏一项 App 白屏）：`webDir: dist`、`server.androidScheme: 'http'`、`server.cleartext: true`；
iOS 侧 `Info.plist` 需 `NSAllowsArbitraryLoads`，Android 需 `android:usesCleartextTraffic="true"`。

---

## 9. 非功能与边界

| 类别 | 约束 |
| --- | --- |
| 网络 | 仅局域网/组网；`ALLOW_CIDR` 白名单；不做端口映射 |
| 数据备份 | 每日 `pg_dump -Fc` + 文件 tar，保留 14 份，季度演练恢复 |
| 性能目标 | 食材百级、批次千级、流水万级；列表接口 P95 < 300ms |
| 时区 | 数据库 UTC，业务日期按 `Asia/Shanghai` |
| 兼容 | Safari 16+ / Chrome 110+；iOS 16+ / Android 10+ |
| 单点风险 | NAS 单机；靠每日备份与可重放流水兜底 |

---

## 10. 架构决策记录（ADR 摘要）

| 决策 | 结论 | 主要理由 |
| --- | --- | --- |
| 数据库 | PostgreSQL 而非 SQLite | 金额需 `NUMERIC` 精确到分；需行级锁与视图 |
| 后端语言 | Python/FastAPI 而非 Node | 多表事务 + 强校验 + 定时任务；且本机 pip 可用 |
| 认证 | 配对码而非密码/Passkey | 个人自用、无公网、NAS 权限即管理员；Passkey 需域名+HTTPS |
| 前端 | Vue 3 + TS | PRD 指定；一套产物供 Web 与 App |
| 前端形态 | 打包进 App，不走远程 URL | 秒开、可显示缓存、可用原生能力 |
| 提醒 | App 本地通知 | 绕开 PWA 的 HTTPS 限制 |
| 容器数 | 2 个 | 减少故障面 |

完整论证见 `docs/final-plan.md`。
