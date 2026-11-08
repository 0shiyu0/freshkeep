# 鲜度 FreshKeep · 功能实现方案与技术选型（v4）

> **前提已定**：认证采用**配对码**（一次性 6 位码 → 设备令牌）。
> 因此**不再需要域名与 HTTPS**，地址形态回到"填 IP 直连"；代价是放弃 PWA 的离线与"安装应用"能力（见 §1.13）。
> 本文把剩余功能逐一拆到"关键技术 / 模块划分 / 数据交互 / 边界处理"，并给出跨平台组件与选型依据。
> 上一版 `docs/architecture.md` 的 Passkey 章节自本文起仅作技术备查。

---

## 0. 一张图看数据怎么流

```
浏览器 / App（WebView，同一套 WebUI）
   │  ① 启动：GET /api/v1/state  → 内存缓存（items + settings + 汇总）
   │  ② 交互：先改内存 → 立刻重绘 → 再发请求（乐观更新）
   ▼
Node 服务（单进程）
   │  ③ 中间件：ALLOW_CIDR → 令牌 → 限流 → 写请求校验 Origin
   │  ④ 路由 → 业务函数 → 事务（BEGIN IMMEDIATE）→ 追加流水
   ▼
SQLite（WAL）
   │  ⑤ 返回权威结果（qty / delta / 新 updated_at）
   ▼
客户端拿到结果校正缓存；失败则回滚内存并 toast
```

三条硬规则贯穿全文：

1. **库存数量只有一个真值**，在 `items.qty`；流水是它的变更日志；
2. **所有写操作都是"追加事件"**，不是"覆盖状态"——多端同时操作自然合并；
3. **每个写请求带 `op_id`**，弱网重试不会重复扣减。

---

## 1. 功能方案逐项拆解

### 1.1 认证与设备配对（配对码）

| 项 | 内容 |
| --- | --- |
| 关键技术 | `crypto.randomBytes` 生成码与令牌；`crypto.createHash('sha256')` 存哈希；`timingSafeEqual` 常数时间比较 |
| 核心模块 | `server/auth.js`（发码/验码/签发令牌/校验/吊销）、`server/enroll.js`（命令行重发码） |
| 数据表 | `devices(id, name, token_hash, created_at, last_seen_at, revoked_at)`、`pair_codes(code_hash, expires_at, used_at)` |

**配对流程**

```
① 首次启动（devices 表为空）：生成 6 位码（字符集去掉 0/O/1/I/L，避免手抄错）
   → console.log("配对码：4K7T2M（10 分钟内有效）") → 存 SHA-256
② 客户端填 IP → GET /api/v1/ping → {paired:false}
③ POST /api/v1/pair { code, deviceName }
   服务端：查哈希 → 未过期 → 未使用 → 标记已用 → 生成 32 字节令牌
   回包：网页 Set-Cookie（HttpOnly, SameSite=Lax, 不带 Secure——因为走 HTTP）
        App 回 body 里的 token，存 Preferences（WebView 同源则同样用 Cookie）
④ 之后每个请求：middleware 取 Cookie 或 Authorization，比哈希、查吊销、刷新 last_seen（5 分钟一次）
```

**边界处理**：码错 5 次锁该 IP 5 分钟（内存计数）；令牌只在签发时明文出现一次；网页与 App 走同一套 Cookie 机制（因为 App 的 WebView 与服务器同源），
所以**不需要给 App 单独做 Bearer 注入**——这是配对码方案比 Passkey 简单的地方之一。

---

### 1.2 库存台账（列表 / 分组 / 搜索）

| 项 | 内容 |
| --- | --- |
| 关键技术 | SQLite 索引（`deleted_at, expiry`）+ 服务端排序 + 前端全量缓存渲染 |
| 核心模块 | `server/repo/items.js`（查询与映射）、`js/store.js`（内存态）、`js/app.js`（`viewInventory`） |
| 数据流 | `GET /state` → 一次性拿全量（示例 14 KB）→ 前端分组排序 → 渲染 |

**为什么全量而不是分页**：家庭食材量级在百件以内，一次拉全（<50 KB gzip）比分页简单得多，
也让"搜索/筛选"完全在前端做，零请求延迟。只有当 items > 2000 时才需要考虑分页（阈值写进文档，避免以后误判）。

**排序规则（纯函数，可测）**：有保质期的按 `daysLeft` 升序（已过期在最前）→ 无保质期的按名称 → 同日内按 `updated_at` 降序。

---

### 1.3 快速录入

| 项 | 内容 |
| --- | --- |
| 关键技术 | 前端常量表（`PRESETS`）+ 表单填充，不涉及网络直到提交 |
| 核心模块 | `js/app.js` 的 `PRESETS` 与 `openForm()` |
| 数据流 | 点芯片 → 写 DOM（名称/分类/单位/建议保质期）→ 用户只改数量 → `POST /items` |

**关键技术点**：芯片是"本地字典"，永不请求服务端；因此新增常用食材要改前端常量并重新部署（可接受）。
建议保质期用"今天 + N 天"生成，**不要用"保质期 = 生产日期 + 天数"**——家庭场景里用户只记得"大概还能放几天"。

---

### 1.4 消耗（核心写路径）

| 项 | 内容 |
| --- | --- |
| 关键技术 | SQLite `BEGIN IMMEDIATE` 事务；`op_id` 唯一约束做幂等；`UPDATE ... SET qty` 单语句扣减 |
| 核心模块 | `server/repo/consume.js` |
| 数据流 | 前端 `opId = uuid()` → `POST /items/:id/consume {amount,type,note,opId}` → 事务 → 返回 `{qty, delta, log}` |

```js
db.exec('BEGIN IMMEDIATE');                       // 立即取写锁，避免读到旧 qty
const it = db.prepare('SELECT qty, base_factor FROM items WHERE id=? AND deleted_at IS NULL').get(id);
const after = Math.max(0, it.qty - amount);       // 夹到 0，永不出现负库存
if (after === it.qty) { db.exec('ROLLBACK'); return { delta: 0 }; }  // 已空：不写流水
db.prepare('UPDATE items SET qty=?, updated_at=? WHERE id=?').run(after, Date.now(), id);
db.prepare('INSERT INTO logs (...) VALUES (...)').run(...);          // op_id UNIQUE
db.exec('COMMIT');
```

**幂等实现**：捕获 `UNIQUE constraint failed: logs.op_id` → 回查该 `op_id` 的流水并返回同一结果（HTTP 200），
客户端重试拿到的是"已处理"而不是报错。这是弱网下不重复扣减的唯一可靠做法。

**已验证**：库存 2 用 9 → `{delta:-1, qty:0}`；库存 0 再用 → `{delta:0}` 且不写流水。

---

### 1.5 补货 / 丢弃 / 盘点修正

同一事务模板，差异只在 `type` 与校验：

| 操作 | type | 数量语义 | 特殊校验 |
| --- | --- | --- | --- |
| 消耗 | `use` | 减少量 | 夹到 0 |
| 补货 | `restock` | 增加量 | 无上限 |
| 丢弃 | `waste` | 减少量 | 必须 `qty > 0`，否则提示"没有可丢弃的" |
| 盘点 | `adjust` | **提交实际数量**，服务端反算 `delta = 实际 − 当前` | 客户端不得传 delta |

盘点的设计考虑：如果客户端传差值，两台设备同时盘点会叠加出错；传实际值则天然幂等（同样的实际值提交两次，第二次 delta=0）。

---

### 1.6 撤销

| 项 | 内容 |
| --- | --- |
| 关键技术 | 读流水 → 反向回滚 → 删流水，同一事务 |
| 关键点 | 回滚用 `qty = max(0, qty − delta)`；`delta` 带符号，所以 `use`/`restock`/`waste`/`adjust` 用同一段代码 |

**为什么不软删流水**：撤销的语义是"这笔没发生过"，留着会让统计重复计算。审计需求由"谁在什么时候撤销了什么"记到服务端日志（stdout 即可），不占用业务表。

---

### 1.7 临期提醒

| 项 | 内容 |
| --- | --- |
| 关键技术 | **服务端**计算 `daysLeft`（容器 `TZ=Asia/Shanghai`），随 `/state` 下发 `daysLeft` 字段 |
| 核心模块 | `server/repo/items.js` 的 `withDaysLeft()` |
| 分段 | 已过期（<0）/ 紧急（0~3）/ 本周（4~7），阈值存 `settings` 表 |

**为什么服务端算**：客户端时区可能不是东八区（笔记本出差、模拟器 UTC），前端各自算会出现"同一件食材两台设备显示不同剩余天数"。
服务端统一按容器时区算，前端只做展示与分组。

**边界**：无保质期的食材不参与；开封后的食材若配置了 `opened_at`，用 `opened_at + 开封后保质期` 覆盖原 `expiry`（P2）。

---

### 1.8 位置维度

| 项 | 内容 |
| --- | --- |
| 关键技术 | `items.location` 枚举（冷藏/冷冻/常温/橱柜）+ 复合索引 |
| 用途 | 列表可按位置分组；临期页可按位置筛"冷冻层先吃哪盒" |
| 边界 | 位置是**自由枚举**（用户可增），存在 `settings` 的 JSON 里，不做独立表——家庭场景下位置种类不超过 8 个 |

---

### 1.9 单位换算与统计

| 项 | 内容 |
| --- | --- |
| 关键技术 | 每个食材自带 `base_unit` + `base_factor`；写流水时同时记 `amount`（展示口径）与 `base_amount = amount × base_factor`（统计口径） |
| 核心模块 | `server/repo/stats.js`（聚合）、纯函数 `baseAmount(amount, factor)` |
| 双口径 | ① 按**笔数**（跨品类可比）② 按**基准量**（同类合计，如"这周 2.1 kg 肉"） |

```sql
SELECT date(at/1000,'unixepoch','localtime') AS d,
       COUNT(*)          AS uses,      -- 口径①
       SUM(base_amount)  AS base       -- 口径②
FROM logs
WHERE type='use' AND at >= ?
GROUP BY d ORDER BY d;
```

**边界**：未配置 `base_unit` 的食材 `base_amount` 记 0，统计时归入"仅按次"；避免把"个"和"斤"直接相加这种无意义数字。

---

### 1.10 补货清单

| 项 | 内容 |
| --- | --- |
| 关键技术 | 派生数据 + 手动干预：`shopping_items(source, item_id, name, qty_hint, done_at, sort)` |
| 生成逻辑 | ① 库存 ≤ 阈值 ② 临期未处理 ③ 用户手动添加；三项合并去重 |
| 交互 | 勾选完成 → 可"一键转补货"（对已有食材调 `restock`，对新食材走 `POST /items`） |

**为什么落表而不是纯派生**：纯派生无法记住"我已经买了但还没入库"的状态，也无法手工排序。落表 + `source` 字段保留自动来源，用户删掉后不再自动加回（记 `dismissed_at`）。

---

### 1.11 导入导出与备份

| 项 | 内容 |
| --- | --- |
| 关键技术 | 服务端生成 JSON/CSV（流式写，不整段拼接）；`VACUUM INTO` 做在线备份 |
| 端点 | `GET /export/json`、`GET /export/csv`、`POST /import?mode=replace\|merge` |
| CSV | 带 UTF-8 BOM，Excel 直接打开不乱码；字段含逗号/引号时按 RFC 4180 转义（现有实现已测） |
| 备份 | 每日 03:00 `VACUUM INTO /data/backups/freshkeep-<stamp>.db`，保留 14 份 |

**恢复**：停容器 → 覆盖 `freshkeep.db` → **同时删除 `-wal` / `-shm`** → 启动。WAL 存在时只覆盖主文件会读到旧数据。

---

### 1.12 WebUI 与 App 的同步策略

| 场景 | 策略 |
| --- | --- |
| 正常 | 乐观更新：改内存 → 重绘 → 提交 → 用服务端返回的 `qty` 校正 |
| 提交失败（4xx） | 回滚内存 + toast 展示服务端错误文案 |
| 提交失败（网络） | 回滚内存 + 提示"已离线，改动未保存"；不排队（家用 NAS 常在线，排队重放的复杂度不值） |
| 只读降级 | `localStorage` 留最近一次 `/state` 快照，接口不通时只读展示 + 顶部横幅"离线快照" |
| 多端一致 | 页面重新可见（`visibilitychange`）时拉一次 `/state`；不做 WebSocket（数据量小、频率低，轮询式刷新足够） |

**明确不做**：离线写入队列、CRDT 合并、WebSocket 实时推送。三者的复杂度都远超这个项目的收益。

---

### 1.13 一个必须提前接受的取舍：PWA 能力

Service Worker 只在**安全上下文**（HTTPS 或 localhost）注册。配对码方案走 `http://IP:8080`，因此：

| 能力 | 结果 |
| --- | --- |
| 离线缓存 | ✗ 不可用 |
| Chrome/Android 的"安装应用" | ✗ 不满足安装条件（需要 SW + HTTPS） |
| iOS Safari"添加到主屏幕" | ✓ 可用，但只是书签式全屏，**无离线** |
| 手机端离线体验 | 由原生 App 承担（App 本身可离线启动，只是数据要联网取） |

如果以后想要 PWA 离线，唯一的办法是给局域网加自签证书（P2 可选项），不影响配对码本身。

---

## 2. 服务端模块划分（文件级）

```
server/
├── index.js        # 入口：创建 http server、装配中间件、注册路由、启动迁移
├── config.js       # 环境变量读取与默认值（PORT/DATA_DIR/ALLOW_CIDR/TZ）
├── db.js           # 打开 SQLite、PRAGMA、迁移、事务助手 tx()
├── migrations/     # 001_init.sql、002_locations.sql …（按 user_version 顺序执行）
├── http/
│   ├── router.js   # 极简路由（method + 路径模式 → handler），约 80 行
│   ├── static.js   # 静态文件（mime 表、ETag=mtime、gzip）
│   ├── body.js     # JSON 解析 + 1MB 上限
│   └── errors.js   # HttpError → JSON 响应
├── middleware/
│   ├── cidr.js     # ALLOW_CIDR 白名单
│   ├── auth.js     # Cookie/Bearer 校验、last_seen 刷新
│   └── ratelimit.js# IP 维度计数（内存 Map + 定期清理）
├── repo/
│   ├── items.js    # 查询、映射、daysLeft
│   ├── consume.js  # 消耗/补货/丢弃/盘点的事务
│   ├── logs.js     # 流水查询与撤销
│   ├── stats.js    # 聚合（双口径）
│   └── export.js   # JSON/CSV 生成（流式）
├── routes/         # auth.js / items.js / logs.js / stats.js / admin.js
└── tasks/
    ├── backup.js   # 定时 VACUUM INTO + 清理
    └── enroll.js   # 命令行重发配对码
```

**请求管线（顺序固定，缺一层就有对应风险）**

```
ALLOW_CIDR（网段）→ 静态资源直出 → /api：body 解析 → 认证 → 限流 → Origin 校验（仅写操作）→ 路由
```

---

## 3. 跨平台组件与软件清单

### 3.1 服务端运行时

| 候选 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| **Node.js 24 LTS** | 与前端同语言；内置 `node:sqlite`/`node:crypto`/`node:http`；官方 alpine 镜像成熟；`node --test` 内置 | 启动比 Bun 慢（毫秒级，可忽略） | ✅ **选它** |
| Bun | 内置 SQLite、性能更高、单文件打包 | 镜像生态较新；`node:sqlite` 之外的另一套 API，踩坑无人兜 | 备选（若将来需要单文件分发） |
| Deno | 内置 kv/sqlite、默认安全模型 | 与现有代码风格差异大；部署镜像非官方 | 不选 |

**数据库驱动**：`node:sqlite`（内置，零依赖）✅ / `better-sqlite3`（npm，性能更好但需 native 编译或 prebuild）。
**改选条件**：需要 Node 20 或更低版本时，换 `better-sqlite3`（它是唯一成熟的同步 SQLite 驱动）。

### 3.2 HTTP 层与数据库

| 项 | 选择 | 依据 | 备选/改选条件 |
| --- | --- | --- | --- |
| HTTP 框架 | **原生 `node:http` + 自写 80 行路由** | 路由总数 < 25 条，引入框架的收益小于依赖成本 | 需要 schema 校验/插件生态时换 Fastify |
| 数据库 | **SQLite（WAL）** | 单机单用户；备份=拷文件；写入低频 | 多用户/多机时换 PostgreSQL |
| 迁移 | **手写 `PRAGMA user_version` + 顺序 SQL** | 迁移次数个位数，Alembic 级工具过重 | 迁移超过 20 个时换 knex/umzug |
| 定时任务 | **`setInterval` + 启动补偿** | 只有备份一个任务，不需要 cron 库 | 任务超过 3 个时换 node-cron |

### 3.3 WebUI

| 项 | 选择 | 依据 |
| --- | --- | --- |
| 框架 | **原生 JS + 模板字符串**（现状保留） | UI 已完成并验证；0 依赖、0 构建；数据量小，全量重绘足够 |
| 构建工具 | **无** | 没有编译步骤 = 改完刷新即见，也省掉 CI 构建链 |
| 样式 | **原生 CSS + CSS 变量** | 单文件 900 行，已有设计系统 |
| 状态管理 | **单例模块 + 全量重绘** | 比引入 Redux/Pinia 简单一个数量级 |

**改选条件**：页面数超过 8 个或需要复杂表单联动时，引入 Vue 3 + Vite（届时构建链才值得）。

### 3.4 移动端框架（关键选型）

| 候选 | 复用 WebUI | 包体积 | 原生能力 | 构建复杂度 | iOS 自签友好度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| **Capacitor 6** | 100% | ~8 MB | 插件齐全（Preferences/Network/Splash） | 低（`npx cap sync`） | 高（工程可见可改，不锁工具链） | ✅ **选它** |
| React Native | 0（要重写） | ~20 MB | 最全 | 高（Metro/Pod/Gradle 三套） | 中 | 不选：等于重写 UI |
| Flutter | 0（要重写） | ~15 MB | 最全 | 中 | 中（需 Flutter SDK） | 不选：本机无 SDK，且要重写 |
| Tauri Mobile | 100% | ~5 MB | 中（Rust 侧） | 高（需 Rust 工具链） | 中 | 不选：生态尚早，iOS 侧不稳 |
| 纯 PWA | 100% | 0 | 无 | 无 | — | 不选：HTTP 下装不了（§1.13） |

### 3.5 Android 工具链

| 组件 | 版本 | 作用 | 说明 |
| --- | --- | --- | --- |
| JDK | 17 或 21 | 编译与运行 Gradle | Capacitor 6 要求 JDK 17+ |
| Android SDK | compileSdk 34 / minSdk 23 | 编译目标与最低支持 | minSdk 23 覆盖 Android 6+，够用 |
| Gradle | 8.x（随工程） | 构建 APK | 用 wrapper，不依赖全局安装 |
| keystore | 自建 `.jks` | 签名，保证覆盖升级 | **必须单独备份** |
| adb / 文件传输 | 可选 | 真机调试与安装 | 也可直接下载 APK 安装 |

### 3.6 iOS 工具链

| 组件 | 版本 | 作用 | 约束 |
| --- | --- | --- | --- |
| macOS + Xcode | Xcode 15+ | 编译、归档 | **本机只有 CLT，没有 Xcode → 本地出不了包** |
| CocoaPods / SPM | — | Capacitor iOS 依赖管理 | Capacitor 6 默认用 SPM，可选 CocoaPods |
| `xcodebuild` | 随 Xcode | 命令行归档 | 在 CI 的 macOS runner 上执行 |
| GitHub Actions `macos-14` | — | 出**未签名 IPA** | 免费额度足够，单次约 5 分钟 |
| 自签工具 | Sideloadly / ESign / 爱思助手 | 用长期证书重签 | 需 `.p12` + 描述文件；企业证书免 UDID |

### 3.7 CI / 部署

| 组件 | 作用 | 选择依据 |
| --- | --- | --- |
| GitHub Actions（ubuntu） | 构建镜像、跑服务端测试 | 与仓库同源，零额外账号 |
| GitHub Actions（macos-14） | 出未签名 IPA | 唯一能跑 `xcodebuild` 的免费手段 |
| Docker + Compose v2 | NAS 上单容器运行 | fnOS 自带；`restart: unless-stopped` + healthcheck |
| buildx（可选） | 多架构镜像（amd64/arm64） | 若 NAS 是 ARM 或想直接拉镜像 |
| Caddy（可选） | 自签/自动证书的 HTTPS 反向代理 | 只有将来想开 PWA 离线时才需要 |

### 3.8 运行环境矩阵

| 环境 | 要求 |
| --- | --- |
| NAS | fnOS，Docker 24+，≥512 MB 可用内存，1 个空闲端口（默认 8080） |
| 服务端镜像 | `node:24-alpine`（约 50 MB，无 npm 安装步骤） |
| 电脑浏览器 | Safari 16+ / Chrome 110+ / Edge 110+（需支持 `fetch`、`Intl`、CSS `:has` 可选降级） |
| iOS | 16+（Capacitor 6 最低要求） |
| Android | 10+（minSdk 23 兜底，实际测试以 10+ 为准） |
| 网络 | 局域网直连，或 Tailscale/ZeroTier 组网；**不需要外网** |

---

## 4. "要装什么"总清单

| 场景 | 需要安装 |
| --- | --- |
| **只跑服务端**（最小） | Docker + Compose。镜像里已含 Node，**无需 npm** |
| **开发服务端** | Node 24（或 22.5+）、`git`、可选 `curl`/`httpie` |
| **开发 WebUI** | 同上，加一个静态服务器（`python3 -m http.server` 即可） |
| **构建 Android** | JDK 17+、Android SDK、Gradle（wrapper 自带）、keystore |
| **构建 iOS** | 装了 Xcode 的 Mac，**或**直接用 GitHub Actions（本机零安装） |
| **手机安装** | Android：APK 直装；iOS：自签工具 + 证书 |

**依赖库（npm）清单**

| 层 | 依赖 | 说明 |
| --- | --- | --- |
| 服务端 | **0 个** | 目标是不引入任何 runtime 依赖 |
| WebUI | **0 个** | 无框架、无构建 |
| App | `@capacitor/core` `@capacitor/cli` `@capacitor/android` `@capacitor/ios` `@capacitor/preferences` `@capacitor/network` `@capacitor/splash-screen` `@capacitor/status-bar` `@capacitor/app` | 只为原生壳服务，不进入业务代码 |
| 开发期（可选） | `eslint` `prettier` | 只在本地跑，不进镜像 |

---

## 5. 选型取舍汇总

| 决策 | 选了 | 没选 | 触发改选的条件 |
| --- | --- | --- | --- |
| 运行时 | Node 24 | Bun / Deno | 需要单文件分发 → Bun |
| 数据库 | SQLite（内置驱动） | PostgreSQL / `better-sqlite3` | 多用户并发写 → PG；Node < 22.5 → better-sqlite3 |
| HTTP | 原生 `node:http` | Express / Fastify | 路由 > 25 条或需 schema 校验 → Fastify |
| 前端 | 原生 JS，无构建 | Vue / React + Vite | 页面 > 8 个 → Vue 3 + Vite |
| 移动端 | Capacitor | RN / Flutter / Tauri | 需要重度原生动画或系统级集成 → RN |
| App 与后端通信 | WebView 直接加载服务器地址（同源 Cookie） | 本地资源 + Bearer + CORS | 需要离线优先 → 改本地资源 + 同步队列 |
| 实时性 | 可见时拉 `/state` | WebSocket / SSE | 多端同时编辑同一食材 → 加 SSE |
| 离线 | 只读快照 | 写入队列 + 合并 | 经常在无网环境记账 → 引入队列 |
| 通知 | 应用内提醒 | 推送（APNs/FCM） | 需要"到点提醒我" → 加本地通知（Capacitor Local Notifications，免推送证书） |

---

## 6. 与既有文档的关系

| 文档 | 状态 |
| --- | --- |
| `docs/architecture.md` | 保留：容器化、数据库事务、IP 直连适配、iOS 打包与自签、备份与排障仍然有效；**认证章节（Passkey）已被本文 §1.1 取代** |
| 本文 `docs/implementation-plan.md` | 功能实现的唯一依据 |
| `README.md` | 面向使用者，保持"纯前端版可独立使用"的说明 |

---

## 7. 建议的开工顺序

1. `server/db.js` + `migrations/001_init.sql` + `node --test` 骨架（先把数据库跑通）
2. `consume.js` + 幂等 + 撤销（核心写路径，先把最难的逻辑测通）
3. `auth.js` 配对 + 中间件（一跑起来就能用真机访问）
4. `routes/*` 其余接口 + `static.js` 托管现有 WebUI
5. WebUI 存储层换 HTTP（此时浏览器端可用，可以开始真实记账）
6. Capacitor 壳 + Android APK
7. iOS CI 出未签名 IPA + 自签
8. 备份任务、位置、单位换算、补货清单

前 5 步做完就是一个"值得每天用"的系统；6~8 是把它搬到手机上并补齐长期运维。
