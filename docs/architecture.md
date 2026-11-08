# 鲜度 FreshKeep · 服务端 + 客户端部署方案

> 目标形态：NAS 上一个 Docker 容器（Node 服务 + SQLite + WebUI 同进程），
> 电脑用浏览器访问，手机用独立 App（填服务器 IP）访问，局域网与异地组网都能用。

本文是**实施方案**，不是概念介绍：每节都给到可直接落地的文件、SQL、接口与配置片段。
文中标注「已验证」的部分，是在本机 Node 22.22.2 + `node:sqlite`（SQLite 3.51.2）上实跑过的。

---

## 0. 一页结论

| 组件 | 选型 | 关键理由 |
| --- | --- | --- |
| 服务端运行时 | Node 24（镜像 `node:24-alpine`） | 与现有 WebUI 同语言；镜像小 |
| 数据库 | SQLite（`node:sqlite` 内置驱动，WAL 模式） | 家庭单用户、单机写入；**零 npm 依赖**，容器构建不需联网装包 |
| WebUI | 现有静态页面，换掉存储层 | UI 已打磨完，只需把 localStorage 换成 HTTP |
| 容器 | 单容器，`/data` 挂卷 | 备份 = 拷一个目录；无常驻外部依赖 |
| 电脑访问 | 浏览器 → `http://NAS_IP:8080` | 零安装 |
| 手机访问 | Capacitor 壳 App，首屏填 IP | 一套代码出 Android/iOS，WebView 复用 WebUI |
| 认证 | 设备配对码 → 设备令牌 | 单用户场景，不需要账号体系 |
| 外网 | 优先异地组网（Tailscale/ZeroTier），不映射公网端口 | 免证书、免攻击面 |
| iOS 出包 | GitHub Actions（macOS runner）出**未签名 IPA**，你自签 | 本机只有 CLT 没有 Xcode，本地出不了包 |

**一句话架构**：数据只有一份，在 NAS 容器的 SQLite 里；浏览器和 App 都是它的视图层。

---

## 1. 整体架构

```
                    ┌──────────────────── NAS（飞牛 fnOS · Docker）────────────────────┐
                    │                                                                 │
  浏览器（电脑）      │   ┌───────────── 容器 freshkeep ─────────────┐                    │
  Safari/Chrome ────┼──▶│  Node HTTP 服务（单进程）                 │                    │
                    │   │   ├─ /api/v1/*   业务接口                 │                    │
  手机 App           │   │   ├─ /            静态 WebUI（SPA）      │                    │
  （Capacitor 壳）───┼──▶│   └─ /api/v1/health  健康检查             │                    │
                    │   │            │                              │                    │
  异地组网           │   │            ▼                              │                    │
  Tailscale ────────┼──▶│  SQLite  /data/freshkeep.db（WAL）        │                    │
                    │   │  定期 VACUUM INTO /data/backups/*.db       │                    │
                    │   └───────────────────────────────────────────┘                    │
                    │              ▲ 挂载：/vol1/docker/freshkeep/data                    │
                    └──────────────┼──────────────────────────────────────────────────┘
                                   │
                          反向代理（可选，仅公网暴露时）
                          Caddy + 域名 + Let's Encrypt
```

### 1.1 为什么是"单容器 + 单进程"

- **一致性最简单**：库存数和流水必须在同一事务里改，跨进程就要分布式事务，家庭规模完全不值得。
- **备份最简单**：备份就是拷 `/data`，恢复就是放回去重启。
- **部署最简单**：NAS 上一条 `docker compose up -d`，没有 Redis/Postgres 要维护。
- **性能足够**：家用写入是每天几十次，SQLite WAL 的并发读能力远超需求。

### 1.2 三种接入方式（按推荐顺序）

| 方式 | 手机/电脑填的地址 | 需要什么 | 风险 |
| --- | --- | --- | --- |
| **A. 局域网** | `http://192.168.31.198:8080` | 同 Wi-Fi | 无 |
| **B. 异地组网**（推荐做外网） | `http://100.x.y.z:8080`（Tailscale）或 `http://nas:8080`（MagicDNS） | 两端装 Tailscale/ZeroTier | 流量端到端加密，但依赖中转节点 |
| **C. 公网直连** | `https://fk.你的域名.com` | 域名 + 端口映射 + 反代 + 证书 | 端口暴露、证书维护、被扫描 |

**明确建议**：外网就用 B。原因不是"简单"，而是 **B 不需要在公网上开任何端口**，也不依赖 IP 直连时的明文传输——
组网隧道本身已经加密，此时服务端继续用 HTTP 也不会泄露内容。C 只在你确实需要"任何人打开就能访问"时才做。

---

## 2. 容器与运行时

### 2.1 目录结构（仓库内）

```
freshkeep/
├── index.html            # WebUI（现状保留）
├── css/ js/ icons/       # WebUI 资源（现状保留）
├── server/
│   ├── index.js          # HTTP 服务 + 路由 + 静态托管
│   ├── db.js             # SQLite 打开、迁移、事务封装
│   ├── auth.js           # 配对、令牌、限流
│   ├── api.js            # 业务接口
│   └── schema.sql        # 建表 DDL（随代码版本迁移）
├── Dockerfile
├── docker-compose.yml
└── docs/
```

### 2.2 Dockerfile（零 npm 依赖，构建不需要联网装包）

```dockerfile
FROM node:24-alpine

WORKDIR /app
ENV NODE_ENV=production PORT=8080 DATA_DIR=/data

# 只拷代码，没有 npm install
COPY server ./server
COPY index.html ./index.html
COPY css ./css
COPY js ./js
COPY icons ./icons
COPY manifest.webmanifest sw.js ./

RUN mkdir -p /data/backups \
 && addgroup -S app && adduser -S app -G app \
 && chown -R app:app /app /data

USER app
EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8080/api/v1/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# --experimental-sqlite：Node 22 必需，23.4+ 起可不加，保留以兼容
CMD ["node", "--experimental-sqlite", "server/index.js"]
```

> **已验证**：`node:sqlite` 的 `DatabaseSync` 支持建表、`BEGIN IMMEDIATE` 事务、唯一约束、`date(at/1000,'unixepoch','localtime')` 聚合，
> 本机 Node 22.22.2 + SQLite 3.51.2 实测通过。选它而不是 `better-sqlite3`，是为了让镜像构建**完全不依赖 npm registry**——
> NAS 拉不到 npm 或很慢时，这个差别就是"能不能部署"。

### 2.3 docker-compose.yml

```yaml
services:
  freshkeep:
    build: .
    # 有预构建镜像时可改为：image: ghcr.io/0shiyu0/freshkeep:latest
    container_name: freshkeep
    restart: unless-stopped
    ports:
      - "8080:8080"          # 只在内网/组网可达；不要在路由器上做端口映射
    environment:
      TZ: Asia/Shanghai
      DATA_DIR: /data
      PAIR_CODE: ""          # 留空 = 首次启动随机生成 6 位码并打印到日志
      SESSION_DAYS: "180"    # 设备令牌有效期
      ALLOW_ORIGIN: ""       # 需要跨域（本地调试 WebUI）时填 Origin
    volumes:
      - ./data:/data         # 数据库 + 备份都在这一个目录里
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:8080/api/v1/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 30s
      timeout: 3s
      retries: 3

# fnOS 上 docker compose 插件若不可用，等价命令：
# docker build -t freshkeep . && docker run -d --name freshkeep --restart unless-stopped \
#   -p 8080:8080 -e TZ=Asia/Shanghai -v /vol1/docker/freshkeep/data:/data freshkeep
```

### 2.4 环境变量一览

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PORT` | 8080 | 监听端口 |
| `DATA_DIR` | /data | 数据库与备份目录 |
| `PAIR_CODE` | 随机 6 位 | 首次配对码；已配对后忽略 |
| `SESSION_DAYS` | 180 | 令牌有效期，到期需重新配对 |
| `BACKUP_KEEP` | 14 | 备份保留份数 |
| `TRUST_PROXY` | 0 | 反代后置 1，用于读取 `X-Forwarded-For` 做限流 |

---

## 3. 数据库设计

### 3.1 关键决策

| 决策 | 取值 | 原因 |
| --- | --- | --- |
| 引擎 | SQLite（WAL） | 单机、单用户、写入低频；读并发足够 |
| 库存字段 | `items.qty` 原地存 | 与现有前端模型一致，查询简单 |
| 流水 | `logs` 追加写 | 撤销 = 反向回滚；统计 = 聚合 |
| 删除食材 | **软删除**（`deleted_at`） | 多端同步时，硬删除会被别的端"复活" |
| 幂等 | `logs.op_id UNIQUE` | 弱网重试不会重复扣库存 |
| schema 版本 | `PRAGMA user_version` | 升级时按版本号顺序执行迁移 |

### 3.2 DDL（已验证可执行）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS items (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  emoji       TEXT NOT NULL DEFAULT '🍽️',
  category    TEXT NOT NULL DEFAULT '其他',
  qty         REAL NOT NULL DEFAULT 0 CHECK (qty >= 0),   -- 唯一真值
  unit        TEXT NOT NULL DEFAULT '个',
  expiry      TEXT,                                        -- 'YYYY-MM-DD' 或 NULL
  threshold   REAL NOT NULL DEFAULT 1,
  note        TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  deleted_at  INTEGER                                      -- 软删除
);
CREATE INDEX IF NOT EXISTS idx_items_alive ON items(deleted_at, expiry);

CREATE TABLE IF NOT EXISTS logs (
  id         TEXT PRIMARY KEY,
  item_id    TEXT NOT NULL,
  name       TEXT NOT NULL,          -- 快照：食材删除后历史仍可读
  emoji      TEXT NOT NULL,
  unit       TEXT NOT NULL,
  type       TEXT NOT NULL CHECK (type IN ('use','restock','waste')),
  amount     REAL NOT NULL CHECK (amount > 0),   -- 绝对值，供统计
  delta      REAL NOT NULL,                      -- 带符号，供撤销
  note       TEXT NOT NULL DEFAULT '',
  at         INTEGER NOT NULL,
  device_id  TEXT,
  op_id      TEXT UNIQUE                         -- 幂等键
);
CREATE INDEX IF NOT EXISTS idx_logs_at   ON logs(at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_item ON logs(item_id, at DESC);

CREATE TABLE IF NOT EXISTS settings (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,          -- "时雨的 iPhone" / "书桌 Chrome"
  kind         TEXT NOT NULL DEFAULT 'app',  -- app | web
  token_hash   TEXT NOT NULL UNIQUE,   -- 只存 SHA-256，不存明文令牌
  created_at   INTEGER NOT NULL,
  last_seen_at INTEGER,
  revoked_at   INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
```

### 3.3 写操作的事务形态（已验证）

所有改库存的请求都走同一个事务模板，**先扣库存再写流水，任一步失败整体回滚**：

```js
function consume(db, { itemId, amount, type, note, opId, deviceId }) {
  db.exec('BEGIN IMMEDIATE');            // 立即取写锁，避免并发下读到旧 qty
  try {
    const it = db.prepare('SELECT * FROM items WHERE id=? AND deleted_at IS NULL').get(itemId);
    if (!it) throw new HttpError(404, '食材不存在');

    const after = type === 'restock' ? it.qty + amount : Math.max(0, it.qty - amount);
    const delta = Math.round((after - it.qty) * 100) / 100;
    if (delta === 0) { db.exec('ROLLBACK'); return { delta: 0 }; }  // 已空，不产生流水

    db.prepare('UPDATE items SET qty=?, updated_at=? WHERE id=?').run(after, Date.now(), itemId);
    db.prepare(`INSERT INTO logs (id,item_id,name,emoji,unit,type,amount,delta,note,at,device_id,op_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`)
      .run(newId(), itemId, it.name, it.emoji, it.unit, type, Math.abs(delta), delta,
           note || '', Date.now(), deviceId, opId || null);
    db.exec('COMMIT');
    return { delta, qty: after };
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
}
```

实测结果：库存 2 → 用 1 → `{delta:-1, qty:1}`；用 9 → `{delta:-1, qty:0}`（夹到 0，不会负库存）；
库存 0 再用 → `{delta:0}`，不写流水；同一 `op_id` 重复提交 → `UNIQUE constraint failed: logs.op_id`，
服务端捕获后返回"已处理"，客户端重试天然幂等。

### 3.4 为什么这样设计能大幅减少多端冲突

**取用库存被设计成"追加事件"而不是"覆盖状态"**：两台设备同时点 `−1`，各自追加一条 `use` 流水并原子扣减，
结果是"扣了 2 次"——这正是用户的本意，不需要任何合并逻辑。

只有"编辑食材"这种覆盖式写入才需要版本号：请求带 `If-Unmodified-Since: <updated_at>`，
服务端发现已被改过就返回 `409`，客户端拉最新值让用户确认。

### 3.5 迁移与备份

```js
// 启动时按 user_version 顺序升级
const MIGRATIONS = [
  /* v1 */ (db) => db.exec(fs.readFileSync(new URL('./schema.sql', import.meta.url), 'utf8')),
  /* v2 */ (db) => db.exec('ALTER TABLE items ADD COLUMN brand TEXT')
];
let v = db.prepare('PRAGMA user_version').get().user_version;
while (v < MIGRATIONS.length) { MIGRATIONS[v](db); v++; db.exec(`PRAGMA user_version = ${v}`); }
```

备份用 SQLite 官方的在线备份方式（不锁库、不中断服务）：

```js
// 每天 03:00 + 每次启动后 1 分钟
db.exec(`VACUUM INTO '${DATA_DIR}/backups/freshkeep-${stamp()}.db'`);
// 保留最近 BACKUP_KEEP 份，删多余
```

恢复：停止容器 → 把备份文件改名成 `freshkeep.db` 覆盖 → 启动。因为开着 WAL，恢复时要把同目录的
`-wal`、`-shm` 一并删掉，否则会回放到旧数据。

---

## 4. API 契约

统一前缀 `/api/v1`，JSON；`Content-Type: application/json`；错误统一 `{ "error": { "code": "...", "message": "..." } }`。
时间戳一律用**毫秒整数**（与现有前端一致），日期字段用 `YYYY-MM-DD` 字符串。

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/ping` | 否 | 连通性探测：`{name,version,api,paired,serverTime}` |
| GET | `/api/v1/health` | 否 | 健康检查（容器用） |
| POST | `/api/v1/pair` | 配对码 | `{code,deviceName,kind}` → `{token,deviceId}`（网页同时 Set-Cookie） |
| GET | `/api/v1/state` | 是 | 全量：`{items,settings,serverTime,revision}` |
| POST | `/api/v1/items` | 是 | 新增食材（可带初始数量，自动写 `restock` 流水） |
| PATCH | `/api/v1/items/:id` | 是 | 编辑（覆盖式，带 `If-Unmodified-Since`，冲突 409） |
| DELETE | `/api/v1/items/:id` | 是 | 软删除 |
| POST | `/api/v1/items/:id/consume` | 是 | `{amount,type,note,opId}` → `{qty,delta,log}` |
| POST | `/api/v1/logs/:id/undo` | 是 | 撤销一条流水并回滚库存 |
| GET | `/api/v1/logs?limit=50&before=<ts>&type=use` | 是 | 分组分页的流水 |
| GET | `/api/v1/stats?days=7` | 是 | 与现有 `stats()` 同结构，服务端聚合 |
| GET | `/api/v1/export/json` `…/export/csv` | 是 | 与现有导出格式保持一致 |
| POST | `/api/v1/import` | 是 | 导入备份（`?mode=replace\|merge`） |
| GET | `/api/v1/devices` | 是 | 已配对设备列表 |
| DELETE | `/api/v1/devices/:id` | 是 | 吊销某个设备 |

错误码：`400` 参数非法 / `401` 未认证或令牌失效 / `403` 配对码错误过多 / `404` 资源不存在 /
`409` 版本冲突或 `op_id` 重复 / `429` 限流。

---

## 5. 认证方式

### 5.1 模型：单用户 + 设备令牌

家里只有一个"账户"，不需要注册登录。安全性靠三件事保证：**配对码只在首次使用、令牌可吊销、令牌不落明文**。

```
① 服务端首次启动
   docker logs freshkeep | grep 配对码
   → 配对码 6 位（如 4K7T2M），10 分钟有效，一次性

② 客户端填写 IP → GET /api/v1/ping  → paired:false
③ 输入配对码 → POST /api/v1/pair {code, deviceName, kind}
   → 200 { token: "fk_<32字节base64url>", deviceId }
   → 网页：同时下发 Set-Cookie: fk_session=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=...
   → App：token 存 iOS Keychain / Android Keystore（Capacitor 的 secure storage），后续请求带 Authorization: Bearer

④ 之后每次请求：中间件校验 token 的 SHA-256 是否在 devices 表且未吊销
   → 刷新 last_seen_at（每 5 分钟一次，避免写放大）
```

### 5.2 三种客户端的凭据形态

| 客户端 | 凭据 | 存放 | 优点 |
| --- | --- | --- | --- |
| 电脑浏览器 | Cookie（HttpOnly + SameSite=Lax） | 浏览器 | 刷新免登、JS 读不到，防 XSS 窃取 |
| 手机 App（WebView） | Cookie（同上，因为同源） | WKWebView/WebView 数据目录 | 与浏览器一致，无需注入 token |
| 需要脚本/curl 调用 | Bearer token | 手动保存 | 便于自动化 |

**关键点**：App 的 WebView 直接导航到服务器地址，页面 origin 就是 `http://NAS_IP:8080`，
所以**不需要 CORS、不需要把 token 注入前端 JS**——这是选"远程 URL 模式"的最大好处（见 §7.4）。

### 5.3 防滥用

- 配对接口：同一 IP 5 次失败 → 锁 5 分钟（内存计数即可，重启清零可接受）。
- 令牌校验：常时间比较（`crypto.timingSafeEqual`）。
- 请求体上限 1 MB；`import` 接口上限 10 MB。
- 所有写接口要求 `Content-Type: application/json`，顺带挡掉简单 CSRF。
- 反代部署时加 `TRUST_PROXY=1`，限流按真实 IP。

### 5.4 威胁模型（说清楚边界）

| 场景 | 保护 |
| --- | --- |
| 局域网内有人扫到 8080 | 需要令牌，未配对拿不到数据；`/ping` 只暴露产品名和版本 |
| 手机丢了 | 在设置页吊销该设备，令牌立刻失效 |
| 数据库文件被拿走 | 文件里有明文数据 → 所以 `/data` 必须有 NAS 权限保护；敏感的话开 SQLCipher |
| 公网暴露 | **必须 HTTPS**。明文 HTTP 在公网等于把令牌交给运营商和任何中间人 |
| 异地组网 | 隧道已加密，服务端继续 HTTP 是可接受的 |

---

## 6. WebUI 与数据库的配合

### 6.1 职责划分

```
浏览器/WebView
  ┌─────────────────────────────┐
  │ ui（现有 app.js）            │  只读内存里的 state，改动后全量重绘
  │ store（改造后的门面）        │  乐观更新 + 失败回滚 + 同步队列
  └──────────┬──────────────────┘
             │ HTTP /api/v1
  ┌──────────▼──────────────────┐
  │ server/api.js               │  校验 → 事务 → 返回权威结果
  └──────────┬──────────────────┘
  ┌──────────▼──────────────────┐
  │ SQLite（唯一真值）           │
  └─────────────────────────────┘
```

**真值在服务端，前端内存态是它的副本。** 前端不做"本地也算一遍再合并"，避免两套算法结果不一致。

### 6.2 存储层替换：保持 `FreshKeep` 接口不变

现有 `js/store.js` 暴露的是同步接口（`items()`、`consume()`、`stats()`）。改造后**保持这些函数签名**，
内部从"读写 localStorage"改成"读写内存缓存 + 异步同步"，`app.js` 一行都不用改：

```js
// js/store.js（改造版）
let state = { items: [], logs: [], settings: {} };   // 内存副本
const queue = [];                                     // 待同步操作

export function items() { return state.items.slice(); }        // 同步返回缓存
export function consume(id, amount, type, note) {
  const it = getItem(id);
  const before = it.qty;
  it.qty = Math.max(0, before - amount);              // ① 乐观更新
  const result = { item: it, delta: it.qty - before }; // ② 立即返回给 UI
  flush();                                             // ③ 触发重绘
  sync('/api/v1/items/' + id + '/consume', { amount, type, note, opId: uuid() })
    .catch(() => { it.qty = before; flush(); toast('同步失败，已回滚'); });  // ④ 失败回滚
  return result;
}
```

启动时先 `GET /api/v1/state` 填充缓存 → 渲染；之后所有写操作走上面这条"乐观更新 → 后台提交 → 失败回滚"。

### 6.3 离线与弱网

- **不做完整离线编辑**。理由：服务端是唯一真值，家里 NAS 常年在线；真离线的价值远低于双向同步的复杂度。
- 但要做**降级可读**：`localStorage` 里留一份上次的 `state` 快照，接口不通时以只读模式展示，顶部提示"当前为离线快照"。
- 断网时的写操作：进入队列（IndexedDB），联网后按 `op_id` 幂等重放；超过 24 小时的丢弃并提示。

### 6.4 旧数据迁移

现有用户（你自己）浏览器里已有 `localStorage['freshkeep.v1']` 的数据。
WebUI 首次连上新服务端且本地有数据时，弹一次"把本机 12 种食材上传到服务器？"，
复用现有的 `POST /api/v1/import`（`mode=merge`，按 `id` 去重）。上传成功后标记 `migrated=true`，不再询问。

---

## 7. IP 直连的适配处理

这是"填个 IP 就能用"最容易出问题的地方，分四层处理。

### 7.1 地址规范化（客户端第一道）

```
输入 → 输出
192.168.31.198            → http://192.168.31.198:8080
192.168.31.198:9000       → http://192.168.31.198:9000
http://nas.local/         → http://nas.local:8080
https://fk.example.com    → https://fk.example.com   （443 不补端口）
::1 / [fd00::1]           → http://[fd00::1]:8080    （IPv6 必须加方括号）
 乱输                      → 立即报错，不发请求
```

规则：去首尾空格与末尾斜杠 → 无协议补 `http://` → 无端口且协议是 http 补 `:8080` → IPv6 补方括号。
**顺带把"粘贴带不带斜杠/带不带端口"这种最常见的手输错误都吃掉。**

### 7.2 连通性探测

```http
GET /api/v1/ping
200 {"name":"freshkeep","version":"1.0.0","api":1,"paired":true,"serverTime":1762590000000}
```

客户端用它做四件事：确认这是鲜度的服务（`name`）、版本兼容（`api` 主版本不符就提示升级而不是白屏）、
是否需要配对（`paired`）、服务器时间与本地差多少（时区错乱时提醒）。

### 7.3 多地址与自动回退

App 里保存的是**地址列表**，不是一个地址：

```json
{ "urls": [
    "http://192.168.31.198:8080",
    "http://nas.local:8080",
    "http://100.64.12.7:8080"
  ],
  "lastOk": "http://192.168.31.198:8080",
  "lastOkAt": 1762590000000 }
```

启动/回到前台时：先试 `lastOk`（3 秒超时），失败就并行探测其余地址（取最先成功的），全失败才显示连接页。
这样从"家里 Wi-Fi"切到"外面用组网"时，用户不需要手动改 IP。

### 7.4 明文 HTTP 的平台限制（必读）

| 平台 | 限制 | 处理 |
| --- | --- | --- |
| iOS / WKWebView | ATS 默认禁止明文；**对 IP 字面量的行为在不同 iOS 版本上不一致** | 显式放开（下方针对自签分发可接受；上架 App Store 会被拒） |
| Android 9+ | 默认禁止明文 | manifest 或 `network_security_config` 放开 |
| 浏览器 | 无明文限制；但 `https` 页面里请求 `http` 会被当混合内容拦掉 | WebUI 与 API 同源同协议，天然规避 |

iOS `Info.plist`：

```xml
<key>NSAppTransportSecurity</key>
<dict>
  <!-- WebView 加载远程 http 页面必须 -->
  <key>NSAllowsArbitraryLoadsInWebContent</key><true/>
  <key>NSAllowsArbitraryLoads</key><true/>
  <!-- 允许 .local / 本地网络访问 -->
  <key>NSAllowsLocalNetworking</key><true/>
</dict>
<key>NSLocalNetworkUsageDescription</key>
<string>用于连接你家局域网内的鲜度服务器</string>
```

Android `AndroidManifest.xml`：

```xml
<application
    android:usesCleartextTraffic="true"
    android:networkSecurityConfig="@xml/network_security_config" ...>
```

`res/xml/network_security_config.xml`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <!-- Android 只支持按「具体域名/IP」放行，不支持网段（CIDR）写 192.168.0.0/16 -->
  <!-- 地址由用户运行时输入，无法预知，所以家用场景直接全局放行明文 -->
  <base-config cleartextTrafficPermitted="true">
    <trust-anchors><certificates src="system"/></trust-anchors>
  </base-config>
</network-security-config>
```

> 兜底建议：如果以后要收窄，把服务器改用自签 HTTPS（把 CA 证书打进 App 的 trust-anchors），
> 就能把 `cleartextTrafficPermitted` 关掉。限于"用户随便填 IP"的场景，先全局放行更省事。

### 7.5 WebView 加载模式的选择

| 模式 | 首屏 | 认证 | 跨域 | 离线 | 结论 |
| --- | --- | --- | --- | --- | --- |
| **远程 URL**（导航到 `http://ip:8080`） | 依赖网络 | Cookie 天然可用 | 不存在（同源） | 无 | ✅ 采用 |
| 本地资源 + 调 API | 秒开 | 需注入 Bearer | 需完整 CORS | 可只读 | 复杂度高，暂不做 |
| Capacitor `server.url` 配置 | 依赖网络 | Cookie 可用 | 同源 | 无 | 与方案一等价，但官方定位为调试用，不推荐生产 |

采用"本地连接页 + 导航到服务器"：App 首屏是本地页面（填 IP、扫码、最近地址），
连上后整页导航到服务器，之后所有交互都在服务器 origin 里，Cookie 直接生效。

---

## 8. 移动端 App 设计

### 8.1 选型

| 方案 | 复用现有 WebUI | 双端 | 本地构建难度 | 结论 |
| --- | --- | --- | --- | --- |
| **Capacitor**（推荐） | 100%（WebView） | ✅ | 低（只需 node + Android SDK / Xcode） | 采用 |
| React Native / Flutter | 需重写 UI | ✅ | 高（本机无 Flutter，无 Xcode） | 不划算 |
| 纯 PWA | 100% | ✅ | 无 | 不能自定义"填 IP"首屏、iOS 无后台、无法自签安装 |

Capacitor 的本质是"原生壳 + WebView"，壳只负责：**连接页、安全存储、网络状态、状态栏/启动图、更新检查**。

### 8.2 页面结构

```
┌─ 首屏（本地） ─────────────┐      ┌─ 连接成功后（远程 WebUI） ─┐
│  🥕  鲜度                  │      │  与电脑浏览器完全一致      │
│  ┌──────────────────────┐  │      │  （同一套 HTML/CSS/JS）    │
│  │ 服务器地址            │  │  →   │                          │
│  │ 192.168.31.198:8080  │  │      │  ＋ 原生浮层：断线时提示   │
│  └──────────────────────┘  │      │     "重连 / 换地址"        │
│  [测试连接]  [连接]        │      └──────────────────────────┘
│  最近使用：客厅 NAS ✓      │
│  或 扫码配对（二维码）      │
└───────────────────────────┘
```

### 8.3 App 侧要做的原生增强（按优先级）

1. **安全存储**：令牌放 Keychain/Keystore（`@capacitor/preferences` 不够安全，用 `capacitor-secure-storage-plugin`）。
2. **网络状态监听**：`@capacitor/network` → 网络恢复时自动重连 + 重新探测地址。
3. **下拉刷新 & 返回键**：Android 物理返回键在 WebView 里不能直接退出 App。
4. **生物识别解锁**（可选）：Face ID 打开 App 时再放行一次，防手机被他人拿去看库存（家庭数据，优先级低）。
5. **快捷记一笔**（可选）：iOS Shortcuts / Android 桌面小组件，直接调 `POST /consume`。

---

## 9. Android 发布流程

### 9.1 一次性准备：签名密钥

```bash
keytool -genkeypair -v -keystore freshkeep.jks -alias freshkeep \
  -keyalg RSA -keysize 2048 -validity 10000
```

`.jks` 文件与口令要单独备份——**丢了就无法覆盖升级**（只能卸载重装，数据在服务端所以不丢，但体验很差）。

### 9.2 构建

```bash
# 本机（需 Android SDK + JDK）
cd app && npx cap sync android
cd android && ./gradlew assembleRelease     # 产物：app/build/outputs/apk/release/app-release.apk
```

签名配置放 `android/keystore.properties`（不进仓库），`build.gradle` 读取即可。

### 9.3 分发与更新

- 把 APK 放到 NAS 的 Web 目录（`/api/v1/app/android`），手机浏览器直接下载安装（需允许"未知来源"）。
- **覆盖安装的前提**：签名相同 + `versionCode` 递增。所以每次发版记得改 `versionCode`。
- 也可以在 App 内做"检查更新"：`GET /api/v1/ping` 返回最新版本号，比本地高就提示去下载。

---

## 10. iOS 打包与自签

### 10.1 现实约束

本机**只有 Command Line Tools，没有 Xcode**，`xcodebuild` 不可用 → 本地出不了 IPA。
可行路径只有两条：① 另一台装了 Xcode 的 Mac；② **GitHub Actions 的 macOS runner**（推荐，免费额度够用）。

### 10.2 出"未签名 IPA"（CI）

```yaml
# .github/workflows/ios.yml
name: ios-unsigned
on: [workflow_dispatch]
jobs:
  build:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 24 }
      - run: cd app && npm ci && npx cap sync ios
      - name: Archive without signing
        run: |
          cd app/ios/App
          xcodebuild -workspace App.xcworkspace -scheme App \
            -configuration Release -sdk iphoneos \
            -archivePath $RUNNER_TEMP/App.xcarchive \
            CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
            archive
      - name: Package unsigned ipa
        run: |
          mkdir -p $RUNNER_TEMP/Payload
          cp -R $RUNNER_TEMP/App.xcarchive/Products/Applications/App.app $RUNNER_TEMP/Payload/
          cd $RUNNER_TEMP && zip -qry App-unsigned.ipa Payload
      - uses: actions/upload-artifact@v4
        with:
          name: App-unsigned-ipa
          path: ${{ runner.temp }}/App-unsigned.ipa
```

要点：

- `CODE_SIGNING_ALLOWED=NO` 出的是**未签名**包，`Payload/App.app` 里没有 `_CodeSignature`。
- 打包必须保留目录结构 `Payload/App.app/...`，否则任何重签工具都认不出来。
- **ATS 配置写在 `Info.plist` 里，重签不影响**，所以 §7.4 的明文放行会跟着包走。

### 10.3 用长期证书自签

| 证书类型 | 需要 UDID | 有效期 | 适用 |
| --- | --- | --- | --- |
| **企业证书（In-House）** | 不需要 | 证书 1~3 年，随时可能被吊销 | 你说的"长期证书"多半是这种，装完即用 |
| 付费个人/公司开发者 | **需要**把设备 UDID 注册进描述文件 | 证书 1 年、描述文件 1 年 | 稳定，每年续 |
| 免费 Apple ID | 需要 | **7 天**，需 AltStore 之类自动续签 | 临时试用 |

自签步骤（以 Sideloadly / ESign / 爱思助手 为例，逻辑一致）：

1. 导入 `App-unsigned.ipa`；
2. 选择证书 `.p12` + 描述文件 `.mobileprovision`（企业证书通常只要 `.p12`）；
3. **Bundle ID** 与证书的 App ID 匹配（用通配符 `com.0shiyu0.*` 最省心）；
4. 重签会重写 `embedded.mobileprovision` 与 `_CodeSignature/`，并把 entitlements 换成证书允许的集合；
5. 安装到设备 → **设置 → 通用 → VPN与设备管理 → 信任**该证书；
6. iOS 16+ 还要在 **设置 → 隐私与安全性 → 开发者模式** 打开，否则点开就闪退。

### 10.4 常见失败点（按出现频率排序）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 装完点开闪退 | 证书未信任 / 开发者模式未开 / entitlements 与证书不匹配 | 先信任证书，再开开发者模式，最后看 Console 日志 |
| 安装时报 "Unable to Install" | 描述文件没包含该设备 UDID，或 bundle id 不匹配 | 改用企业证书或注册 UDID |
| 装完过几天打不开 | 证书被吊销 / 7 天到期 | 重新签；避免把 ipa 传到公开分发平台 |
| 页面白屏但能联网 | ATS 拦了明文请求 | 确认 `Info.plist` 三个键都在（§7.4） |
| 找不到服务器 | 手机在蜂窝网、NAS 只有内网 IP | 开异地组网，或在 App 里切换地址 |

### 10.5 分发方式

- 直接 AirDrop / 爱思助手 / ESign 装到自己的设备（最简单）。
- 想无线装：`itms-services://?action=download-manifest&url=https://…/manifest.plist`，**必须 https**，
  所以这条路要先有域名+证书，家庭自用不划算。

---

## 11. 部署与运维

### 11.1 首次部署（NAS 上 5 步）

```bash
# 1. 建目录
mkdir -p /vol1/docker/freshkeep/data

# 2. 取代码（或直接把仓库目录拷进去）
cd /vol1/docker/freshkeep && git clone git@github.com:0shiyu0/freshkeep.git .

# 3. 构建并启动
docker compose up -d --build

# 4. 取配对码
docker compose logs freshkeep | grep -i 配对码

# 5. 浏览器打开 http://<NAS_IP>:8080 → 输入配对码
```

### 11.2 升级

```bash
git pull && docker compose up -d --build
```

数据库迁移在启动时按 `user_version` 自动执行；升级前建议先 `docker compose exec freshkeep node -e "…VACUUM INTO…"` 手动打一份快照。

### 11.3 排障表

| 现象 | 检查 |
| --- | --- |
| 浏览器打不开 | `docker compose ps` 是否 healthy；`curl http://127.0.0.1:8080/api/v1/health` |
| 局域网能开、手机不能 | 手机是否在同一网段 / 是否连了 5G；NAS 防火墙是否放行 8080 |
| App 提示连不上但浏览器能开 | App 里地址少了端口，或填了 `https://` |
| 数据没更新 | 是否两台设备连的是不同实例（容器重建但卷没挂对） |
| 容器反复重启 | `docker compose logs --tail=100`；多为 `/data` 权限（`chown` 失败） |

---

## 12. 实施计划

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| **P0** | `server/`：SQLite + 全部 API + 静态托管 + 配对认证；Dockerfile/compose；WebUI 存储层换成 HTTP（保留离线快照） | 能 `docker compose up` 跑起来，浏览器可用 |
| **P1** | Capacitor 壳：连接页、地址规范化、多地址回退、安全存储；Android 出 APK；GitHub Actions 出未签名 IPA | 手机装上能用，局域网直连 |
| **P2** | 异地组网文档与实测；自动备份 + 一键恢复脚本；设备管理页；旧数据迁移引导 | 外网可用，运维闭环 |

P0 不做原生壳也能先用——手机浏览器访问同一个地址即可，App 的价值在"免输地址 + 图标入口 + 原生体验"。

---

## 13. 风险与取舍（明确写出来，避免后面踩坑）

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 明文 HTTP | 公网被抓包即泄露令牌与全部数据 | 外网只走组网或反代 HTTPS；局域网可接受 |
| 单容器单进程 | 进程崩溃，App/网页同时不可用 | `restart: unless-stopped` + 健康检查 + 家庭规模无 SLA 要求 |
| SQLite 单写者 | 并发写排队 | WAL + `busy_timeout=5000`；家用并发极低 |
| 企业证书被吊销 | 已装的 iOS App 全部打不开 | 保留重签流程；重要数据在服务端，重装即恢复 |
| 没有 Xcode | 本地无法出 IPA | CI（macOS runner）出未签名包 |
| ATS 放开明文 | 若将来上架 App Store 会被拒 | 仅作自签分发；上架需改成 HTTPS + 收窄 ATS |
| NAS 单点 | 硬盘坏 = 数据没了 | `/data` 每日 `VACUUM INTO` + 建议再同步一份到网盘/另一台设备 |
