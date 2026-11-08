# 鲜度 FreshKeep · 最终开发方案（定稿）

> **本文是全项目唯一依据。** 与 `docs/architecture.md`、`docs/implementation-plan.md`、`docs/prd-alignment.md` 冲突时，以本文为准
> （前三者是过程文档，保留作技术备查）。
> 输入：`家庭食材库存与营养管理系统_PRD及技术设计_V1.0.docx` + 后续三轮决策（Passkey 评估 → 配对码 → PRD 对齐）。
> 本文把已知的 8 处冲突逐条定案，并附对 PRD 的 4 处必要偏离。

---

## 0. 八处冲突的最终决策（一览）

| # | 冲突 | **最终决策** | 一句话理由 |
| --- | --- | --- | --- |
| 1 | 认证方式 | **配对码 → 长期设备令牌**；Web 用 HttpOnly Cookie、App 用 Bearer；**不做密码** | 个人自用、无公网、NAS 权限即管理员权限；少一个弱口令面与重置流程；令牌可吊销 |
| 2 | 产品形态 | **原生 App（APK + 自签 IPA）+ Web 网页**，一套 Vue 前端两处复用 | 你的明确要求；且原生壳能拿到本地通知与图标入口，绕开 PWA 的 HTTPS 死结 |
| 3 | PWA 与 HTTPS | **不做 PWA 安装与系统通知**；提醒改由 **App 本地通知**承载 | Service Worker / Notification 都要安全上下文，HTTP 下不可用；原生 App 直接绕过该限制 |
| 4 | 数据库 | **PostgreSQL 16** | 金额 `NUMERIC(14,2)` 是验收硬指标（10.80 / 42.20），SQLite 无真十进制；另需行级锁与视图 |
| 5 | 后端 | **FastAPI + SQLAlchemy 2.1（同步）+ Pydantic 2 + Alembic + APScheduler** | 本机 pip 可用（已实测）；多表事务 + 强校验 + 定时任务正是这套栈的强项 |
| 6 | 前端 | **Vue 3.5 + TS + Vite 8 + Pinia 4 + Naive UI + ECharts 6** | PRD 指定；npm 可用（已实测），一套产物同时供 Web 与 App |
| 7 | 计量模型 | **数量 / 重量双维度独立余额**，只有配置 `default_unit_weight` 才联动 | PRD §5.3 与验收用例"单位不匹配拒绝换算"要求如此 |
| 8 | 库存真值 | **余额由流水可重算**，批次余额是缓存字段 + 每日对账任务 | PRD §5.1；可追溯到每一笔分配，撤销靠反向流水 |

### 对 PRD 的 4 处必要偏离（均由冲突 1~3 推导，不是遗漏）

| # | PRD 原本 | 最终做法 | 原因 |
| --- | --- | --- | --- |
| D1 | §9 密码用 Argon2id/bcrypt；`users.password_hash`；`/auth/login`、`/auth/change-password` | 不实现密码登录；`users` 表保留但只有一行 `owner`，`password_hash` 字段保留且恒为 `NULL`；新增 `/auth/pair`、`/auth/devices` | 见 §2 的论证。保留字段与表，是为了将来要加密码时不需要数据迁移 |
| D2 | PWA 安装 + 系统通知 | 不做 PWA；`notifications` 表保留，语义改为「App 本地通知的调度记录」 | 见 §4 |
| D3 | 5 个容器（frontend / backend / postgres / caddy / ai-worker / backup-worker） | **2 个容器**（api / db）：`frontend` 由 api 静态托管；caddy 推迟到上 TLS 时；ai-worker 与 backup-worker 合并进 api 的 APScheduler | 家庭单机场景，容器数越少故障面越小；AI 识别是 P2，届时再加 worker |
| D4 | Cookie 用 `HttpOnly + Secure + SameSite` | P0 只有 `HttpOnly + SameSite=Lax`，**没有 `Secure`** | HTTP 下带 `Secure` 的 Cookie 会被浏览器直接丢弃。P1 上 TLS 后补 `Secure` |

---

## 1. 产品形态与交付物

| 端 | 形态 | 访问方式 | 凭据 |
| --- | --- | --- | --- |
| 电脑 | 浏览器打开 `http://<NAS_IP>:8080` | 同源 | HttpOnly Cookie |
| Android | APK 直装 | 填地址 → 配对 | Bearer（Keystore） |
| iOS | 未签名 IPA + 你用长期证书自签 | 填地址 → 配对 | Bearer（Keychain） |

**交付物清单**：`docker-compose.yml` + 两个镜像；Alembic 迁移；`freshkeep-<ver>.apk`；`FreshKeep-unsigned.ipa`；
FastAPI 自带的 `/docs`（OpenAPI）；9 条验收用例的测试报告；NAS 部署与备份恢复手册。

---

## 2. 冲突 1：认证 —— 为什么选「配对码 + 设备令牌」而不是密码

### 2.1 三个候选的对比

| 方案 | 新增代码 | 攻击面 | 加设备的成本 | 忘记凭据的成本 | 符合 PRD |
| --- | --- | --- | --- | --- | --- |
| 密码（PRD 原方案） | 密码哈希 + 改密 + 重置流程 ≈ 2.5 人日 | 弱口令、撞库、明文过网（HTTP） | 输一次密码 | 需要重置流程（要么另开接口、要么改库） | ✅ |
| **配对码 + 设备令牌** | 配对码 + 令牌 + 设备表 ≈ 1.5 人日 | 仅一次性短串，10 分钟窗口 | NAS 上执行一条命令 | 同样一条命令（你有 shell 权限） | 需偏离 |
| Passkey | ≈ 5 人日 + 强制 HTTPS/域名 | 最低 | 需域名与证书链 | 有锁死风险，需恢复码 | 需偏离更多 |

### 2.2 决策与理由

**选配对码 + 长期设备令牌。** 三条理由：

1. **权限模型上密码没有增益**：能执行 `docker compose exec` 的人本来就等于系统管理员。密码只保护"能访问 8080 端口但没有 NAS 权限的人"，
   而这类人已经被 `ALLOW_CIDR`（只允许内网/组网网段）挡在外面。密码在这里是"给已经进门的人再加一把门锁"。
2. **少一个长期秘密就少一类故障**：密码会弱、会忘、会被写进便签；它在 HTTP 局域网上还是明文传输。配对码是一次性、10 分钟过期、用后即废，
   泄露窗口从"永久"缩到"分钟级"。
3. **设备令牌才是真正需要长期存在的东西**：手机、平板、电脑各自一枚，各自可吊销、可看最后活跃时间。密码反而是这一层之上的冗余。

### 2.3 最终认证设计

```
① NAS 上执行：docker compose exec api python -m app.cli pair
   → 打印 6 位码（字符集去掉 0/O/1/I/L），10 分钟有效，一次性，只存 SHA-256
② 客户端（Web 或 App）填地址 → POST /api/v1/auth/pair {code, device_name, platform}
   → 服务端校验 → 生成 32 字节令牌（只存 SHA-256）→ devices 表落一行
   → Web：Set-Cookie: fk_sid=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000
   → App：响应体返回 {token}，存 iOS Keychain / Android Keystore
③ 之后：
   Web  → 浏览器自动带 Cookie（同源，无 CORS）
   App  → Authorization: Bearer <token>（跨源，需 CORS）
   服务端依赖：先读 Bearer，再读 Cookie，两者都映射到 devices.id
④ 令牌不过期（个人自用），可在「设置 → 已授权设备」吊销；吊销即时生效（每次请求查 devices.revoked_at）
```

**边界处理**：配对码错 5 次锁该 IP 5 分钟；`devices` 记录 `platform / ip / user_agent / last_seen_at`；
设置页可看"时雨的 iPhone · 最后活跃 3 小时前"并一键吊销；令牌泄露的唯一现实路径是手机丢失 → 吊销即可。

---

## 3. 冲突 2：产品形态 —— 原生 App + Web，一套前端两处用

### 3.1 关键决策：App 打包前端资源，API 跨源走 Bearer

| 做法 | 首屏 | 认证 | 离线 | 结论 |
| --- | --- | --- | --- | --- |
| App 内 WebView 加载远程地址（`server.url`） | 依赖网络 | Cookie 同源，最省事 | 无 | ✗ 不像 App，白屏即失败 |
| **App 打包 `dist` + API 跨源 Bearer** | 本地秒开 | 需 CORS + 令牌存储 | Shell 可用、数据走缓存 | ✅ **采用** |

**为什么 App 不能用 Cookie**：App 的 origin 是 `capacitor://localhost`（iOS）/ `http://localhost`（Android），
向 `http://192.168.x.x:8080` 发请求属于**跨站**。跨站要带 Cookie 必须 `SameSite=None; Secure`，
而 `Secure` 在 HTTP 下会被直接拒绝——这条路在协议层就断了。所以 App 只能用 Bearer。

**为什么 Web 反而用 Cookie**：Web 与 API 同源（都由 api 容器托管），同源 Cookie 不受 `SameSite` 约束，
且 `HttpOnly` 让 XSS 拿不到令牌（PRD §9 也要求"避免长期令牌放在 localStorage"）。

### 3.2 CORS 配置（只放行三个来源）

```python
allow_origins = [
    "capacitor://localhost",      # iOS Capacitor 默认 scheme
    "http://localhost",           # Android（androidScheme 设为 http）
    "http://localhost:5173",      # 开发期 Vite
]
allow_headers = ["Authorization", "Content-Type", "Idempotency-Key"]
allow_credentials = False          # 走 Bearer，不需要带 Cookie
```

### 3.3 移动端必须显式配的三项（漏一项就白屏）

| 平台 | 配置 | 缺了会怎样 |
| --- | --- | --- |
| Android | `android:usesCleartextTraffic="true"` + `server.androidScheme = "http"` | 明文请求被拦 / origin 变成 `https://localhost` 导致混合内容拦截 |
| iOS | `Info.plist` → `NSAllowsArbitraryLoads = true` + `NSLocalNetworkUsageDescription` | ATS 拦掉所有 `http://` 请求 |
| Capacitor | `server.allowNavigation` 不设（因为不发远程导航）、`webDir: dist` | — |

> 明文 HTTP 的边界：只在局域网或组网隧道内可达，不做公网端口映射。要公网就得上 TLS（P1 可选）。

---

## 4. 冲突 3：PWA 与通知 —— 放弃 PWA，用 App 本地通知

- Service Worker 与 Notification API **都要求安全上下文**（HTTPS 或 localhost）。内网 HTTP 访问时两者都不存在，
  所以"PWA 安装 + 系统通知"在 P0 的部署形态下无法实现，这是规范约束，不是实现问题。
- **替代方案**：原生 App 用 `@capacitor/local-notifications`，在每次拉取 `/dashboard/alerts` 时把未来 7 天的临期批次
  排成本地通知（App 打开时排程，不需要推送证书、不需要 FCM/APNs）。Web 端只在页面内显示提醒条。
- `notifications` 表保留为"调度记录"（哪条批次、计划何时提醒、是否已送达），语义从"已推送"改为"已排程"。
- **保留项**：`manifest.webmanifest` 继续提供，iOS/Android 浏览器"添加到主屏幕"仍可用（只是没有离线与通知）——零成本，不做额外承诺。

---

## 5. 冲突 4~8：其余五处决策

| # | 决策 | 理由 | 代价 |
| --- | --- | --- | --- |
| 4 | **PostgreSQL 16**，金额 `NUMERIC(14,2)`、重量/数量 `NUMERIC(14,3)`、营养 `NUMERIC(14,4)`、时间 `TIMESTAMPTZ`（UTC 存储，`Asia/Shanghai` 计算业务日期） | 验收用例要求 10.80 / 42.20 分毫不差；批次并发扣减要 `SELECT … FOR UPDATE`；对账要用视图 | NAS 多一个容器（约 150 MB 内存）、备份要 `pg_dump` |
| 5 | **FastAPI + SQLAlchemy 2.1 同步模式 + Pydantic 2 + Alembic + APScheduler**；驱动 `psycopg 3` | 同步 session 让"事务 + 行锁 + 批量分配"写得直白，也便于 pytest 直接测；异步 session 在这套逻辑里只增加心智负担 | 单进程吞吐上限较低，家庭场景无影响（`uvicorn --workers 2` 足够） |
| 6 | **Vue 3.5 + TypeScript + Vite 8 + Pinia 4 + Naive UI + ECharts 6 + dayjs** | PRD 指定；一套 `dist` 同时给 Web 与 App；Naive UI 对中文/深色模式支持好 | 有构建步骤；TS 会拖慢初期迭代（用 `strict: false` 起步，P1 再收紧） |
| 7 | **双计量**：`quantity` 与 `weight` 两条独立余额；`ingredients.default_unit_weight` 为空时**禁止**任何自动换算 | PRD §5.3 + 验收用例"单位不匹配必须拒绝" | 每个录入/展示都要处理两个值；前端表单更复杂 |
| 8 | **批次余额是缓存**：`batches.remaining_*` 由 `transaction_allocations` 聚合得出，每日 03:00 对账（差异写 `audit_logs` 并告警） | PRD §5.1；撤销/并发都以流水为准 | 多一个对账任务与一份重算 SQL |

---

## 6. 技术栈总表（版本均实测可获取）

| 层 | 组件 | 版本 | 作用 |
| --- | --- | --- | --- |
| 运行时 | Python | 3.12+ | 后端（本机 3.13.12 可用） |
| Web 框架 | FastAPI | 0.162.2 | 路由、OpenAPI 文档、依赖注入 |
| ORM | SQLAlchemy | 2.1.8 | 同步 Session、事务、行锁 |
| 校验 | Pydantic | 2.14.3 | 请求/响应模型、双计量校验 |
| 迁移 | Alembic | 1.20.1 | 数据库版本管理 |
| 驱动 | psycopg | 3.3.8 | PostgreSQL 连接 |
| 定时 | APScheduler | 3.x | 临期扫描、对账、备份 |
| 数据库 | PostgreSQL | 16 | 主存储 |
| 前端框架 | Vue | 3.5.45 | SPA |
| 构建 | Vite | 8.3.6 | 开发服务器 + 产物构建 |
| 状态 | Pinia | 4.1.0 | 全局状态（库存、筛选、鉴权） |
| 组件库 | Naive UI | 2.45.3 | 表格、表单、弹层 |
| 图表 | ECharts | 6.1.0 | 成本/消耗/营养趋势 |
| 移动壳 | Capacitor | 8.6.0 | APK / IPA 打包 |
| 原生插件 | preferences / secure-storage / network / splash-screen / status-bar / app / local-notifications | 随 Capacitor 8 | 令牌存储、网络状态、启动图、返回键、本地通知 |
| 部署 | Docker Compose v2 | — | api + db 两个容器 |
| 测试 | pytest + httpx + factory-boy | — | 单元与接口测试 |

**运行时要求**：NAS 2 GB 可用内存、1 个端口（8080）；开发机 Python 3.12+、Node 20+；
iOS 构建需 **Xcode 16+**（Capacitor 8 要求），本机目前只有 CLT，装完 Xcode 后 `sudo xcode-select -s /Applications/Xcode.app` 生效。

---

## 7. 数据模型（PRD 22 表 + 本项目必需 3 表 = 25 表）

PRD 的 22 张表原样采纳（表名与字段见 PRD §6）。新增 3 张，都是 PRD 未覆盖但实现必需：

| 新增表 | 字段 | 为什么必须有 |
| --- | --- | --- |
| `devices` | id, name, platform, token_hash, ip, user_agent, created_at, last_seen_at, revoked_at | PRD 的 `users` 只有 password_hash，没有设备令牌概念；配对码方案需要它承载"谁被授权" |
| `pair_codes` | id, code_hash, expires_at, used_at, created_at | 一次性配对码，只存哈希 |
| `idempotency_keys` | key, request_hash, status_code, response_json, created_at | PRD §5.5 要求幂等，但没给实现载体 |

**关键索引与约束**

```sql
CREATE UNIQUE INDEX ux_barcode ON ingredient_barcodes(barcode);
CREATE INDEX ix_batches_ingredient_expiry ON batches(ingredient_id, expiry_date) WHERE status = 'active';
CREATE INDEX ix_tx_ingredient_time ON inventory_transactions(ingredient_id, created_at DESC);
CREATE INDEX ix_cons_time ON consumption_records(consumed_at DESC);
ALTER TABLE batches ADD CONSTRAINT ck_batch_nonneg CHECK (remaining_quantity >= 0 AND remaining_weight >= 0 AND remaining_cost >= 0);
ALTER TABLE inventory_transactions ADD CONSTRAINT ck_tx_type CHECK (type IN
  ('purchase','consume','spoilage','adjustment','reverse'));
-- 外键一律 ON DELETE RESTRICT：历史不可物理删除（PRD §3.2）
```

**视图**（首页/库存页/采购建议统一只读它，避免三处各写一遍聚合）

```sql
CREATE VIEW v_inventory AS
SELECT i.id AS ingredient_id, i.name,
       COALESCE(SUM(b.remaining_quantity),0) AS total_quantity,
       COALESCE(SUM(b.remaining_weight),0)   AS total_weight,
       COALESCE(SUM(b.remaining_cost),0)     AS total_cost,
       COUNT(b.id) FILTER (WHERE b.remaining_weight > 0) AS batch_count,
       MIN(b.expiry_date) FILTER (WHERE b.remaining_weight > 0) AS nearest_expiry,
       (COALESCE(SUM(b.remaining_quantity),0) <= i.minimum_quantity) AS is_low_stock
FROM ingredients i LEFT JOIN batches b ON b.ingredient_id = i.id AND b.status = 'active'
WHERE i.is_active GROUP BY i.id;
```

---

## 8. API 契约

基础路径 `/api/v1`；统一响应 `{success, data, message, request_id}`；错误 `{success:false, error:{code,message}, request_id}`。

**认证相关（与 PRD 的差异只在这三个接口）**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/pair` | `{code, device_name, platform}` → Web 下发 Cookie / App 返回 token |
| GET | `/auth/devices` | 已授权设备列表 |
| DELETE | `/auth/devices/{id}` | 吊销（用于"退出登录"与"手机丢了"） |
| ~~POST /auth/login~~ | — | **不实现**（见 §2） |
| ~~POST /auth/change-password~~ | — | **不实现**（无密码） |

其余接口按 PRD §7 的清单实现：分类、食材、批次、消耗、库存（`/inventory/adjustments`、`/stocktake`、`/spoilage`）、
首页 dashboard、统计、营养、文件与 AI、条码、菜谱、采购清单、导出与备份。

**通用约定**：写操作支持 `Idempotency-Key`；分页 `page/page_size/sort_by/sort_order`；
错误码 `VALIDATION_ERROR / NOT_FOUND / INSUFFICIENT_STOCK / DUPLICATE_REQUEST / CONFLICT / UNAUTHORIZED / FORBIDDEN`。

---

## 9. 四个核心算法（实现细节，直接照此写）

### 9.1 FEFO 分配

```python
def allocate(db, ingredient_id, need_weight: Decimal) -> list[Allocation]:
    batches = db.execute(
        select(Batch).where(Batch.ingredient_id == ingredient_id,
                            Batch.status == 'active',
                            Batch.remaining_weight > 0)
        .order_by(Batch.expiry_date.asc().nulls_last(),
                  Batch.purchase_date.asc(), Batch.id.asc())
        .with_for_update()                    # 行级锁，防并发超卖
    ).scalars().all()

    out, left = [], need_weight
    for b in batches:
        if left <= 0: break
        take = min(b.remaining_weight, left)
        # 尾差：本次把该批次扣完 → 直接结清剩余成本，避免残留分币
        cost = b.remaining_cost if take == b.remaining_weight \
               else (take * b.remaining_cost / b.remaining_weight).quantize(Q2)
        out.append(Allocation(batch=b, weight=take, cost=cost))
        left -= take
    if left > 0:
        raise InsufficientStock(shortage=left)   # 抛异常 → 事务整体回滚
    return out
```

三个必须遵守的点：**过滤 `remaining_weight > 0`**（否则除零）、**全程 `Decimal`**（不要 `float`）、
**`with_for_update()` 加在 batches 查询上**（锁顺序固定为 expiry_date，避免死锁）。

### 9.2 双计量联动

```
请求同时带 quantity 与 weight：
  unit_weight = ingredient.default_unit_weight
  若 unit_weight 为空 → 若两者不一致则 422 UNIT_NOT_CONVERTIBLE；一致则接受
  若 unit_weight 非空 → 期望 weight = quantity × unit_weight
       |weight - 期望| > 0.001 → 422 INCONSISTENT_MEASURE
请求只带一个维度：
  unit_weight 为空 → 只能扣该维度，另一维度 delta 记 0
  unit_weight 非空 → 另一维度按换算补齐，并在流水 note 标记 derived=true
```

### 9.3 营养快照

```
consumption_nutrition.actual_value = weight × ingredient_nutrition.value / ingredient_nutrition.basis_amount
```
必须在**消耗事务内**写入快照表；后续修改食材营养档案不得影响历史（PRD §5.4 与验收用例）。

### 9.4 对账（每日 03:00）

```
对每个活跃批次：recalc_weight = Σ transaction_allocations.weight_delta
               recalc_cost   = Σ transaction_allocations.cost_delta
若与 batches.remaining_* 差异 > 0.001 → 写 audit_logs（action='reconcile_mismatch'）并修正缓存
```

---

## 10. 目录结构（monorepo）

```
freshkeep/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 装配、CORS、静态托管 dist
│   │   ├── core/                   # config / security / errors / idempotency / deps
│   │   ├── db/                     # session、base、seed
│   │   ├── models/                 # 25 张表
│   │   ├── schemas/                # Pydantic（含双计量 validator）
│   │   ├── services/               # fefo / cost / nutrition / inventory / reconcile
│   │   ├── api/v1/                 # routers（按 PRD 的模块分文件）
│   │   ├── tasks/                  # APScheduler jobs（临期扫描/对账/备份）
│   │   └── cli.py                  # `python -m app.cli pair` 生成配对码
│   ├── alembic/versions/
│   ├── tests/{unit,api,acceptance}/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/{views,components,stores,api,router,styles}/
│   ├── dist/                       # 构建产物（被 backend 托管，也被 Capacitor 打包）
│   ├── android/  ios/              # Capacitor 原生工程
│   ├── capacitor.config.ts
│   ├── vite.config.ts
│   └── package.json
├── docker-compose.yml
├── .env.example
└── docs/
```

**一套前端两处用**：`npm run build` 产出 `frontend/dist` →
① backend 在启动时挂载 `StaticFiles(directory="../frontend/dist", html=True)`；
② Capacitor 的 `webDir` 指向同一目录，`npx cap sync` 把它复制进原生工程。

---

## 11. 部署

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: freshkeep
      POSTGRES_USER: freshkeep
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      TZ: Asia/Shanghai
    volumes: ["./pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U freshkeep -d freshkeep"]
  api:
    build: ./backend
    restart: unless-stopped
    depends_on: { db: { condition: service_healthy } }
    environment:
      DATABASE_URL: postgresql+psycopg://freshkeep:${DB_PASSWORD}@db:5432/freshkeep
      ALLOW_CIDR: "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10,127.0.0.1/32"
      TZ: Asia/Shanghai
      TZ_BIZ: Asia/Shanghai
    ports: ["8080:8080"]
    volumes: ["./data:/data"]        # 文件资源、导出、备份
```

NAS 目录：`/vol2/docker/food-manager/{docker-compose.yml,.env,pgdata,data}`。
备份：每日 `pg_dump -Fc` 到 `/data/backups/` + 文件目录 tar，保留 14 份；恢复演练每季度一次。

---

## 12. 构建与发布

| 产物 | 命令 | 说明 |
| --- | --- | --- |
| Web | `cd frontend && npm ci && npm run build` | 产物被 api 托管 |
| Android APK | `npx cap sync android && cd android && ./gradlew assembleRelease` | 需 JDK 17 + SDK 34 + keystore（**必须单独备份**，丢了无法覆盖升级） |
| iOS（未签名 IPA） | `npx cap sync ios` → `xcodebuild -workspace App.xcworkspace -scheme App -configuration Release -sdk iphoneos -archivePath build/App.xcarchive CODE_SIGNING_ALLOWED=NO archive` → 组 `Payload/App.app` 压 zip | 需 **Xcode 16+**；产物用 Sideloadly / ESign 以长期证书重签 |
| iOS（Xcode 自动签名） | Xcode → Signing & Capabilities → 选你的证书 → Product → Archive → Export | 有开发者账号时的更短路径，但你要的是自签 IPA，默认走上一行 |

iOS 自签后必做两步：**设置 → 通用 → VPN与设备管理 信任证书**；**iOS 16+ 打开开发者模式**，否则点开即闪退。

---

## 13. 里程碑与工期

| 里程碑 | 范围 | 人日 |
| --- | --- | --- |
| **M0 骨架** | compose（api+db）、Alembic 首迁移、统一响应/错误码、幂等中间件、CORS、静态托管 | 3 |
| **M1 认证** | 配对码 CLI、`/auth/pair`、设备令牌、Cookie/Bearer 双凭据、设备吊销 | 1.5 |
| **M2 档案域** | 分类、单位、食材、条码、储存位置、文件上传 | 3.5 |
| **M3 批次域** | 入库建批次、批次查询、状态流转 | 4 |
| **M4 消耗域**（核心） | FEFO 分配、成本分摊与尾差、双计量联动、事务边界、营养快照 | 5 |
| **M5 库存域** | `v_inventory`、流水、食材详情聚合、对账任务 | 2.5 |
| **M6 首页与营养** | dashboard 四组接口、营养定义/档案/目标、日汇总 | 3 |
| **M7 备份导出** | pg_dump 定时、文件备份、CSV/JSON 导出 | 1 |
| **M8 前端 5 页** | 登录/配对、首页、库存、记录、设置（含图表） | 6 |
| **M9 原生 App** | Capacitor 8 集成、原生配置（ATS/cleartext/CORS/secure storage）、双端出包脚本 | 4 |
| **M10 联调验收** | 9 条验收用例跑绿、时区与边界用例、部署手册 | 2.5 |
| **P0 合计** | | **36 人日** |

P1（临期提醒 + 盘点 + 报损 + 撤销 + 统计页 + 导出 + 扫码 + App 本地通知）≈ 12 人日。
P2（AI 识别 + 采购清单 + 菜谱 + 对账告警 + TLS）≈ 14 人日。
全量约 **62 人日**（单人 + AI 辅助口径，不含需求变更与设计返工）。

---

## 14. 验收标准

**PRD §11 的 9 条必须全绿**，且数字零误差：

| 用例 | 断言 |
| --- | --- |
| 批次成本 | 500g/18元 + 1000g/35元，消耗 300g → 成本 `10.80`，剩余 `42.20` |
| FEFO | A(500g,11-10) + B(1000g,11-20) 消耗 600g → A 清零、B 剩 900g |
| 营养快照 | 165/31/3.6 每100g × 200g → `330 / 62 / 7.2`；改档案不改历史 |
| 库存不足 / 重复 Idempotency-Key / 并发扣减 / 撤销 / 单位不匹配 / 批量回滚 | 分别为 `INSUFFICIENT_STOCK`、返回原响应、无负库存、反向流水、`UNIT_NOT_CONVERTIBLE`、整批回滚 |

**本项目追加**：配对码 10 分钟过期且一次有效；吊销设备后该令牌 1 秒内失效；
App 在飞行模式下打开显示缓存数据而非白屏；`v_inventory` 与批次聚合差值为 0。

---

## 15. 风险与回滚

| 风险 | 概率/影响 | 缓解 | 回滚 |
| --- | --- | --- | --- |
| App 白屏（CORS/ATS/cleartext 配错） | 中/高 | 三处配置写进 §3.3 清单，出包前逐条打勾 | 临时改用 Web 端，App 侧只修配置 |
| 金额精度错误 | 低/高 | 全程 `Decimal` + 验收用例断言到分 | 修复后重跑对账，差异写审计 |
| Xcode 安装后 Capacitor 8 编译失败 | 中/中 | 装 Xcode 16+；保留 GitHub Actions 出包作为备份路径 | 降 Capacitor 到 7 |
| 配对码泄露 | 低/中 | 10 分钟 + 一次有效 + 只看内网 | 吊销该设备令牌 |
| NAS 单点故障 | 中/高 | 每日 pg_dump + 文件备份，保留 14 份 | 按手册恢复，演练过即验证 |
| 前端 TS 严格模式拖慢进度 | 中/低 | P0 用 `strict: false`，P1 收紧 | — |

---

## 16. 内部一致性自检（本文档的交叉核对）

| 检查项 | 结论 |
| --- | --- |
| 认证方式 ↔ API 表 ↔ 数据表 | 配对码方案 ↔ `/auth/pair` + `/auth/devices` ↔ `devices` + `pair_codes`，无 `password_hash` 使用、无 `/auth/login` |
| App 通信 ↔ CORS ↔ 令牌存储 | Bearer ↔ `allow_headers` 含 Authorization ↔ Keychain/Keystore |
| Web 通信 ↔ Cookie ↔ 静态托管 | 同源 ↔ 无需 CORS ↔ `StaticFiles` 挂 dist |
| 提醒 ↔ 产品形态 | 无 PWA ↔ App 本地通知 ↔ `notifications` 表语义为"排程" |
| 数据库 ↔ 金额精度 ↔ 验收用例 | PG `NUMERIC(14,2)` ↔ `10.80 / 42.20` 可精确表达 |
| 计量 ↔ 验收用例 | 双计量 + 禁止自动换算 ↔ `UNIT_NOT_CONVERTIBLE` |
| 库存真值 ↔ 撤销 ↔ 对账 | 流水为准 ↔ 反向流水 ↔ 每日重算比对 |
