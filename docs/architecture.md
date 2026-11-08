# 鲜度 FreshKeep · 自托管方案（v2）

> **v2 相对 v1 的变更**
> 1. **删除公网暴露方案**：不做端口映射、不做反向代理、不做 Let's Encrypt。系统只在局域网或异地组网内可达。
> 2. **认证从"配对码"改为"账号 + 密码"**：首启强制创建管理员，不设默认口令；会话用 HttpOnly Cookie。
> 3. **新增"参考项目对照"**：对标 grocy / mealie 的建模与认证做法，明确借什么、不借什么。
> 4. **数据模型补三个维度**：存放位置、单位换算、盘点修正——直接来自 grocy 的实践。
> 5. **访问控制从"约定"变成"代码"**：网段白名单 `ALLOW_CIDR` + 登录态双闸。

---

## 0. 一页结论

| 组件 | 选型 | 关键理由 |
| --- | --- | --- |
| 运行形态 | NAS 单容器单进程：Node 服务 + SQLite + 静态 WebUI | 扣库存与写流水必须同事务；备份 = 拷一个目录 |
| 数据库 | SQLite（`node:sqlite`，WAL） | 家庭规模；**零 npm 依赖**，镜像构建不碰 registry |
| 认证 | 账号 + 密码（scrypt）+ HttpOnly 会话 Cookie | 你要的形态；无默认口令；会话可吊销 |
| 访问边界 | 仅 LAN / 组网；`ALLOW_CIDR` 白名单兜底 | 不开放公网，攻击面 ≈ 0 |
| 电脑端 | 浏览器 → `http://NAS_IP:8080` | 零安装 |
| 手机端 | Capacitor 壳：填 IP → 填账号密码 | 一套代码出 Android/iOS |
| iOS 出包 | GitHub Actions 出**未签名 IPA**，你用长期证书自签 | 本机只有 CLT，无 `xcodebuild` |

---

## 1. 边界与前提

| 项 | 取值 | 说明 |
| --- | --- | --- |
| 网络可达范围 | 局域网 + 异地组网（Tailscale / ZeroTier） | **不做** 公网端口映射，**不做** 反代与证书 |
| 认证方式 | 账号 + 密码 | 首次启动创建管理员；之后可加家庭成员 |
| 用户数 | 1 个管理员 + 可选 N 个成员（共享同一份库存） | 家庭共享，不做"每人一套库存" |
| 单体/多体 | 单容器、单进程、单数据库文件 | 家庭规模的最优解 |
| TLS | 默认不启用 | 见 §4.4 的理由与可选加固 |

**"不开放公网"在工程上的含义**（三条都要做到，缺一条就是漏洞）：

1. 路由器上**不做** 8080 的端口映射；
2. NAS 防火墙只放行 `192.168.0.0/16`、`10.0.0.0/8`、`172.16.0.0/12`、`100.64.0.0/10`（Tailscale 网段）；
3. 应用层 `ALLOW_CIDR` 白名单，不是白名单来的 IP 直接 403——**即使哪天不小心映射了端口，外网也进不来**。

---

## 2. 架构总览

```
  家里 Wi-Fi                        异地组网（Tailscale/ZeroTier）
  192.168.31.x                      100.64.x.x（隧道加密）
        │                                    │
   电脑浏览器                            手机 App
   （账号密码）                     （地址 + 账号密码）
        └──────────────┬─────────────────────┘
                       ▼
        ┌──────── NAS · Docker 容器 freshkeep ────────┐
        │  Node HTTP 服务（单进程）                    │
        │   ├─ /login                 登录页           │
        │   ├─ /api/v1/auth/*         登录/登出/会话   │
        │   ├─ /api/v1/*              业务接口         │
        │   ├─ /                      WebUI（SPA）     │
        │   └─ 中间件：ALLOW_CIDR → 会话 → 限流        │
        │              │                               │
        │              ▼                               │
        │  SQLite  /data/freshkeep.db（WAL）           │
        │    users / sessions / items / logs / settings│
        │  每日 VACUUM INTO /data/backups/*.db         │
        └──────────────────────────────────────────────┘
```

请求进容器后依次经过三道中间件：

```
① ALLOW_CIDR 判网段  → 不在白名单：403（连登录页都不给）
② 会话校验         → 未登录：302 /login（API 则 401）
③ 写操作 CSRF 校验  → Origin/Referer 与 Host 不一致：403
```

---

## 3. 参考项目对照：借什么、不借什么

| 维度 | grocy | mealie | 本方案 |
| --- | --- | --- | --- |
| 语言/框架 | PHP 8.5 + Slim，SQLite ≥3.40 | Python FastAPI + Vue | Node 24 + 原生 JS（复用现有 WebUI） |
| 领域范围 | 家 ERP：库存、购物清单、食谱、餐食计划、家务、电池、设备 | 食谱 + 餐食计划 + 购物清单 | **只做食材库存与消耗**（垂直、轻） |
| 认证 | 内置账号，**默认 `admin/admin`**，首次登录后必须改密；demo/embedded 模式可关闭认证 | `hasher`（密码哈希）+ `tokens`（令牌）+ `providers`（可插拔身份源） | 账号密码 + scrypt + 会话 Cookie；**禁止默认口令** |
| 前端与 API | 前端**全部**走自家 REST `/api`，内嵌 Swagger | REST API + Vue 前端 | 同样 API-first：网页与 App 共用一套契约 |
| 数据建模 | 产品 / 库存 / 库存流水 / 数量单位 / **单位换算** / **存放位置** | 食谱 / 食材 / 购物清单 / 用户组 / 家庭 | 采纳位置、单位换算、盘点修正；不采纳食谱体系 |
| 迁移 | 版本变化时自动迁移 | Alembic | `PRAGMA user_version` 顺序迁移 |
| 移动端 | 响应式 PWA（明确**不做离线**） | 响应式 Web | 独立 App（填地址 + 账号）——你的差异化需求 |

### 3.1 值得直接借的四个点

1. **存放位置（location）**——grocy 用位置切分库存。我们加一个 `location` 字段（冷藏 / 冷冻 / 常温 / 橱柜），
   价值在"找东西"和"临期按位置分组"：打开冷冻层就知道该先吃什么。
2. **单位换算**——grocy 有独立的数量单位与换算表，解决"1 袋 = 500 g"。
   这条直接补上我们现在的短板：**统计只能数"笔数"，不能加总数量**。加了换算后，"这周用了 1.2 kg 肉"才成立。
3. **流水类型不止消耗/采购**——grocy 的库存流水包含盘点修正、开封等类型。
   我们补两类：`adjust`（盘点修正：实际数了数，与系统不一致）和 `opened`（开封时间，用来推导"开封后 N 天吃完"）。
4. **API-first**——两者前端都跑在自己的公开 API 上。这带来一个额外好处：之后接 Home Assistant、iOS 快捷指令、
   甚至桌面小组件都是免费的。

### 3.2 明确不借的部分

| grocy/mealie 的做法 | 为什么不照搬 |
| --- | --- |
| 默认 `admin/admin` 账号 | 家用 NAS 常年在线，弱口令是最大的实际风险源。改为首启强制创建，密码 ≥8 位且校验强度 |
| 完整食谱/餐食计划体系 | 会把这东西从"每天点一下的工具"变成"要维护的 ERP"。食谱留到 P3，且只做"从库存反推能做什么" |
| 多家庭/多租户（mealie 的 group-household） | 你家只有一个厨房。做一个可选的"成员"维度就够 |
| 离线优先 + 双向同步 | grocy 明确不做离线；我们也只做只读快照（§8.3） |
| 扫码录入 | grocy 自己写明：浏览器摄像头**必须在 HTTPS 下**才可用。我们默认 HTTP，所以扫码是 P3 且需要先上自签 TLS |

---

## 4. 访问控制与认证

### 4.1 账号体系

- **首启**：数据库为空时，`/` 自动跳到 `/setup`，要求创建管理员（用户名 3~20 字符、密码 ≥8 位且不能是纯数字）。
  没有默认账号，没有"admin/admin"。
- **之后**：管理员可在设置页添加成员（`role=member`）。**所有成员共享同一份库存**，
  流水里记录 `user_id`，统计页可以按人筛选（"谁把这盒酸奶喝完了"）。
- **改密**：需要旧密码；改密后吊销该用户其它会话。

密码哈希用 Node 内置 `crypto.scrypt`，不引依赖：

```
存储格式： scrypt$N$r$p$<salt_b64>$<hash_b64>
参数：     N=16384, r=8, p=1, keylen=32, salt=16 字节随机
校验：     timingSafeEqual 比较，常数时间
```

> `N=16384` 是刻意选的：`N=32768` 时 `128·N·r` = 32 MB 正好触到 Node 默认 `maxmem`，需要显式调大，
> 反而增加配置出错面。16 MB 的单次成本（约 50~80 ms）对家用登录足够，也让爆破变得不划算。

### 4.2 登录与会话

```http
POST /api/v1/auth/login
{ "username": "shiyu", "password": "……", "deviceName": "时雨的 iPhone" }

200 OK
Set-Cookie: fk_sid=<32字节 base64url>; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000
{ "user": { "id": "u1", "username": "shiyu", "role": "admin" } }
```

- 会话令牌**只存 SHA-256**（`sessions.token_hash`），库被拿走也无法直接冒用。
- 有效期 30 天，**滑动续期**：每次请求若剩余不足 25 天就顺延（每 6 小时最多写一次，避免写放大）。
- 设备列表页展示：设备名、最后活跃时间、IP、UA，可单独吊销。手机丢了就吊销那一台。
- 登出 = 删会话行（不是只清 Cookie）。

### 4.3 防爆破

| 维度 | 策略 |
| --- | --- |
| 单 IP | 5 次失败 / 5 分钟 → 429，指数退避（5s→15s→60s） |
| 单账号 | 10 次失败 / 小时 → 锁 15 分钟，并记录到登录日志 |
| 成本 | scrypt 本身 ~60 ms/次，天然把爆破速率压到个位数/秒 |
| 记录 | `login_attempts(ip, username, at, ok)`，保留 7 天，设置页可看"最近登录" |

### 4.4 为什么默认不开 TLS

- 局域网内 Wi-Fi 由 WPA2/3 加密，同网段被动嗅探在 WPA3 下基本不可行；
- 异地组网（Tailscale/ZeroTier）本身是端到端加密隧道，HTTP 明文只存在于隧道内部；
- 但**密码明文过网**这件事在"多人共用一个 Wi-Fi（公司/宿舍）"场景下不成立。

所以给一条可选加固路径，而不是默认：

```
把自签 CA 证书挂进容器，Node 用 https 起服务（端口 8443）；
App 侧把 CA 打进 trust-anchors（Android）与描述文件（iOS），
浏览器首次访问点"继续前往"即可。
代价：证书续期要手动；换设备要重新信任。收益：密码与令牌不再明文过网。
```

**判断标准**：只有你一个人用、Wi-Fi 是自己的 → HTTP 够用；家里有租客/宿舍/公司网络 → 上自签 TLS。

### 4.5 "IP 地址"这一层的具体形态

你说的"账户密码加 IP 地址"，我按两头都实现：

| 位置 | 形态 |
| --- | --- |
| App 登录页 | 三行：**服务器地址**（`192.168.31.198:8080` 或 `100.64.12.7:8080`）→ 账号 → 密码；地址与账号都记住，密码可选记住（存 Keychain/Keystore） |
| 网页登录页 | 浏览器地址栏本身就是 IP，页面只填账号密码，但页头显示"当前服务器 `192.168.31.198:8080`"，避免连错了实例还以为数据丢了 |
| 服务端 | `ALLOW_CIDR` 白名单把"只允许内网/组网"变成代码约束（§1） |

---

## 5. 数据库设计

### 5.1 表结构（v2）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ① 账号
CREATE TABLE users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name  TEXT NOT NULL DEFAULT '',
  pwd_hash      TEXT NOT NULL,          -- scrypt$N$r$p$salt$hash
  role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  created_at    INTEGER NOT NULL,
  pwd_changed_at INTEGER NOT NULL,
  disabled_at   INTEGER
);

-- ② 会话（只存令牌哈希）
CREATE TABLE sessions (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash   TEXT NOT NULL UNIQUE,
  device_name  TEXT NOT NULL DEFAULT '',
  ip           TEXT NOT NULL DEFAULT '',
  user_agent   TEXT NOT NULL DEFAULT '',
  created_at   INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  revoked_at   INTEGER
);
CREATE INDEX idx_sessions_user ON sessions(user_id, revoked_at);

CREATE TABLE login_attempts (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ip       TEXT NOT NULL,
  username TEXT NOT NULL,
  at       INTEGER NOT NULL,
  ok       INTEGER NOT NULL
);
CREATE INDEX idx_attempts_ip ON login_attempts(ip, at);

-- ③ 食材
CREATE TABLE items (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  emoji       TEXT NOT NULL DEFAULT '🍽️',
  category    TEXT NOT NULL DEFAULT '其他',
  location    TEXT NOT NULL DEFAULT '常温',      -- 冷藏 / 冷冻 / 常温 / 橱柜
  qty         REAL NOT NULL DEFAULT 0 CHECK (qty >= 0),   -- 以 unit 计的当前量（唯一真值）
  unit        TEXT NOT NULL DEFAULT '个',        -- 展示单位
  base_unit   TEXT NOT NULL DEFAULT '',          -- 统计用的基准单位（g / ml / 个）
  base_factor REAL NOT NULL DEFAULT 1,           -- 1 个展示单位 = base_factor 个基准单位
  expiry      TEXT,
  opened_at   INTEGER,                           -- 开封时间（可推导"开封后保质期"）
  threshold   REAL NOT NULL DEFAULT 1,
  note        TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  deleted_at  INTEGER
);
CREATE INDEX idx_items_alive ON items(deleted_at, expiry);

-- ④ 流水（追加写，永不修改）
CREATE TABLE logs (
  id          TEXT PRIMARY KEY,
  item_id     TEXT NOT NULL,
  name        TEXT NOT NULL,        -- 快照：食材删除后历史仍可读
  emoji       TEXT NOT NULL,
  unit        TEXT NOT NULL,
  type        TEXT NOT NULL CHECK (type IN ('use','restock','waste','adjust','opened')),
  amount      REAL NOT NULL CHECK (amount >= 0),   -- 绝对值，供统计
  delta       REAL NOT NULL,                       -- 带符号，供撤销
  base_amount REAL NOT NULL DEFAULT 0,            -- 折算到基准单位的量（跨单位加总）
  note        TEXT NOT NULL DEFAULT '',
  at          INTEGER NOT NULL,
  user_id     TEXT,
  op_id       TEXT UNIQUE                          -- 幂等键
);
CREATE INDEX idx_logs_at   ON logs(at DESC);
CREATE INDEX idx_logs_item ON logs(item_id, at DESC);

CREATE TABLE settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);
```

### 5.2 单位换算为什么这样做（而不是照搬 grocy）

grocy 用**全局**的 `quantity_units` + `quantity_unit_conversions`，因为同一个产品可能在多个单位间切换
（买是按箱、用是按个）。家用场景里更常见的是"这个食材固定用某个单位，但我想按重量统计"，
所以采用**每个食材自带基准单位与系数**：

```
鸡蛋：  unit=个   base_unit=个   base_factor=1      → 用 3 个 = 3 个
猪肉：  unit=斤   base_unit=g    base_factor=500    → 用 1 斤 = 500 g
牛奶：  unit=盒   base_unit=ml   base_factor=250    → 用 1 盒 = 250 ml
```

写流水时同时记 `amount`（展示口径）与 `base_amount = amount × base_factor`（统计口径）。
统计页因此可以给出两个视图：**按次数**（跨品类可比）与**按基准量**（同类食材合计，如"这周用了 2.1 kg 肉"）。
没配基准单位的食材，`base_amount` 记 0，统计时归入"仅按次"。

### 5.3 流水类型扩充

| type | 含义 | delta 符号 | 界面位置 |
| --- | --- | --- | --- |
| `use` | 吃掉/用掉 | − | 清单上 `−1`、详情页 |
| `restock` | 买回来入库 | + | 详情页"补货" |
| `waste` | 坏了/扔了 | − | 临期页"丢弃" |
| `adjust` | **盘点修正**：实际数与系统不符 | ± | 详情页"盘点"，填实际量，服务端反算差值 |
| `opened` | 开封（不改变数量） | 0 | 临期页"开封了"，用于从开封日重算保质期 |

`adjust` 的实现要点：客户端提交**实际数量**而不是差值，服务端算 `delta = 实际 − 当前`，
这样多端同时盘点也不会叠加出错。

### 5.4 事务模板（已验证）

```js
function consume(db, { itemId, amount, type, note, opId, userId }) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const it = db.prepare('SELECT * FROM items WHERE id=? AND deleted_at IS NULL').get(itemId);
    if (!it) throw new HttpError(404, '食材不存在');
    const after = type === 'restock' ? it.qty + amount : Math.max(0, it.qty - amount);
    const delta = Math.round((after - it.qty) * 100) / 100;
    if (delta === 0) { db.exec('ROLLBACK'); return { delta: 0 }; }
    db.prepare('UPDATE items SET qty=?, updated_at=? WHERE id=?').run(after, Date.now(), itemId);
    db.prepare(`INSERT INTO logs (id,item_id,name,emoji,unit,type,amount,delta,base_amount,note,at,user_id,op_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`)
      .run(newId(), itemId, it.name, it.emoji, it.unit, type,
           Math.abs(delta), delta, Math.abs(delta) * it.base_factor,
           note || '', Date.now(), userId, opId || null);
    db.exec('COMMIT');
    return { delta, qty: after };
  } catch (e) { db.exec('ROLLBACK'); throw e; }
}
```

> **已验证**（Node 22.22.2 + SQLite 3.51.2）：库存 2 → 用 1 → `{delta:-1,qty:1}`；用 9 → `{delta:-1,qty:0}`（夹到 0）；
> 库存 0 再用 → `{delta:0}` 且不写流水；同一 `op_id` 重复 → 唯一约束拦截；`date(at/1000,'unixepoch','localtime')` 聚合正常。

---

## 6. API 契约

前缀 `/api/v1`，JSON。认证类接口不需要会话，其余全部需要。

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/ping` | 否 | `{name,version,api,needsSetup,serverTime}`，App 用来验地址 |
| GET | `/api/v1/setup/status` | 否 | `{needsSetup:true}`（仅当无任何用户） |
| POST | `/api/v1/setup` | 否（仅首次） | 创建管理员，成功后直接建会话 |
| POST | `/api/v1/auth/login` | 否 | `{username,password,deviceName}` → 会话 Cookie |
| POST | `/api/v1/auth/logout` | 是 | 删会话 |
| GET | `/api/v1/auth/me` | 是 | 当前用户 |
| POST | `/api/v1/auth/password` | 是 | 改密（需旧密码），吊销其它会话 |
| GET/DELETE | `/api/v1/sessions` `/sessions/:id` | 是 | 设备列表 / 吊销 |
| GET | `/api/v1/state` | 是 | 全量：`items + settings + 统计摘要` |
| POST / PATCH / DELETE | `/api/v1/items[/:id]` | 是 | 增改删（软删） |
| POST | `/api/v1/items/:id/consume` | 是 | `{amount,type,note,opId}` |
| POST | `/api/v1/items/:id/adjust` | 是 | `{actualQty,note}` 盘点修正 |
| POST | `/api/v1/items/:id/open` | 是 | 记开封时间 |
| POST | `/api/v1/logs/:id/undo` | 是 | 撤销并回滚 |
| GET | `/api/v1/logs` `/stats` | 是 | 流水 / 统计（支持 `?base=1` 按基准量） |
| GET | `/api/v1/export/json` `/export/csv` | 是 | 与现有格式兼容 |
| POST | `/api/v1/import` | 是 | `?mode=replace\|merge` |

错误码：`400` 参数非法 / `401` 未登录或会话失效 / `403` 网段不白名单或 CSRF 校验失败 /
`404` 不存在 / `409` 版本冲突或 `op_id` 重复 / `429` 限流 / `503` 数据库忙。

---

## 7. WebUI 与后端配合

现有 `js/store.js` 的同步签名（`items()`、`consume()`、`stats()`）全部保留，内部从 localStorage
换成"内存缓存 + 乐观更新 → 后台提交 → 失败回滚"，`app.js` 不改：

```js
export function consume(id, amount, type, note) {
  const it = getItem(id), before = it.qty;
  it.qty = Math.max(0, before - amount);        // ① 乐观更新，界面立刻响应
  const res = { item: it, delta: it.qty - before };
  flush();                                       // ② 重绘
  api.post(`/items/${id}/consume`, { amount, type, note, opId: uuid() })
     .catch(() => { it.qty = before; flush(); toast('同步失败，已回滚'); });  // ③ 失败回滚
  return res;
}
```

- 启动：`GET /state` 灌缓存 → 渲染（示例数据 14 KB，不分页）；
- 登录态失效（401）：跳 `/login` 并保留当前标签，登录后回到原位置；
- 离线：只做**只读降级**（localStorage 留快照 + 顶部提示"离线快照"），不做双向同步（与 grocy 的判断一致）；
- 旧数据迁移：本地有 `freshkeep.v1` 且服务器为空时，弹一次"上传本机数据"，走 `POST /import?mode=merge`。

---

## 8. IP 直连与 App 登录页

### 8.1 地址规范化（客户端第一道）

```
192.168.31.198            → http://192.168.31.198:8080
192.168.31.198:9000       → http://192.168.31.198:9000
http://nas.local/         → http://nas.local:8080
[fd00::1]                 → http://[fd00::1]:8080
乱输                       → 立即报错，不发请求
```

### 8.2 两类错误必须分开提示

这是 IP 直连场景最容易被糊在一起的地方：

| 现象 | 文案 | 后续动作 |
| --- | --- | --- |
| 连不上服务器（超时/DNS） | "连不上 `192.168.31.198:8080`：请确认在同一 Wi-Fi 或组网已连接" | 保留地址，允许改地址重试 |
| 连上了但账号密码错 | "账号或密码不正确" | 只清密码框，不清地址 |
| 连上了但 403（不在白名单） | "该网络不在允许范围内" | 提示切到家里 Wi-Fi / 开组网 |

`/api/v1/ping` 就是为区分这三者存在的。

### 8.3 多地址回退

App 保存的是地址列表（内网 IP、`nas.local`、组网 IP），启动时先试上次成功的（3 s 超时），
失败则并行探测其余地址，取最先响应的。从家里切到外网不用手改 IP。

### 8.4 明文 HTTP 的平台配置（不变）

- iOS `Info.plist`：`NSAllowsArbitraryLoads` + `NSAllowsArbitraryLoadsInWebContent` + `NSAllowsLocalNetworking` + `NSLocalNetworkUsageDescription`；
- Android：`android:usesCleartextTraffic="true"`（`network-security-config` **不支持网段**，而地址由用户运行时输入，无法预知）；
- WebView 采用"本地连接页 → 导航到服务器地址"，之后同源，**不需要 CORS、不需要把令牌注入前端**。

---

## 9. 双端发布

### 9.1 Android

```bash
keytool -genkeypair -v -keystore freshkeep.jks -alias freshkeep \
  -keyalg RSA -keysize 2048 -validity 10000
cd app && npx cap sync android && cd android && ./gradlew assembleRelease
```

覆盖升级要求**同签名 + `versionCode` 递增**；`.jks` 与口令单独备份（丢了只能卸载重装）。
APK 放 NAS 供下载：`/download/freshkeep-<ver>.apk`。

### 9.2 iOS（本机无 Xcode，走 CI）

```yaml
- run: cd app && npm ci && npx cap sync ios
- run: |
    cd app/ios/App
    xcodebuild -workspace App.xcworkspace -scheme App -configuration Release -sdk iphoneos \
      -archivePath $RUNNER_TEMP/App.xcarchive \
      CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO archive
- run: |
    mkdir -p $RUNNER_TEMP/Payload
    cp -R $RUNNER_TEMP/App.xcarchive/Products/Applications/App.app $RUNNER_TEMP/Payload/
    cd $RUNNER_TEMP && zip -qry App-unsigned.ipa Payload
```

产物是**未签名 IPA**，用你的长期证书重签（Sideloadly / ESign：导 ipa → 选 `.p12` → bundle id 走通配符）→
装完在「设置 → 通用 → VPN与设备管理」信任证书 → iOS 16+ 打开「开发者模式」。

高频失败点：闪退 = 证书未信任 / 开发者模式未开 / entitlements 不匹配；Unable to Install = 描述文件没含 UDID；
白屏但能联网 = ATS 拦了明文。**ATS 配置在 Info.plist 里，重签不影响**。

---

## 10. 部署与运维

### 10.1 首次部署

```bash
mkdir -p /vol1/docker/freshkeep/data
cd /vol1/docker/freshkeep && git clone git@github.com:0shiyu0/freshkeep.git .
docker compose up -d --build
# 浏览器打开 http://<NAS_IP>:8080 → 自动跳 /setup → 创建管理员
```

`docker-compose.yml` 在 v1 基础上删掉端口映射以外的暴露配置，新增：

```yaml
environment:
  ALLOW_CIDR: "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10,127.0.0.1/32"
  SESSION_DAYS: "30"
  TRUST_PROXY: "0"
```

### 10.2 备份与恢复

```bash
# 每天 03:00（容器内 cron 或 NAS 计划任务）
docker compose exec freshkeep node -e "…VACUUM INTO '/data/backups/'+stamp+'.db'…"
# 保留 14 份，超出删最旧
```

恢复：停容器 → 备份文件改名 `freshkeep.db` 覆盖 → **同时删掉 `-wal`、`-shm`** → 启动。

### 10.3 排障

| 现象 | 检查 |
| --- | --- |
| 浏览器打不开 | `docker compose ps`；`curl 127.0.0.1:8080/api/v1/ping` |
| 手机打不开、电脑能开 | 手机是否同网段/组网是否连上；`ALLOW_CIDR` 是否包含组网网段 |
| 登录后立刻掉线 | Cookie 是否被浏览器拦截（HTTP 下 Secure 属性不能设）；系统时间是否偏差过大 |
| 403 且能 ping 通 | 不在 `ALLOW_CIDR`，或写在反向代理后面的真实 IP 没读到（`TRUST_PROXY`） |

---

## 11. 范围与分期

| 阶段 | 内容 | 完成标志 |
| --- | --- | --- |
| **P0** | 服务端：SQLite + 账号体系（setup/login/logout/会话）+ 全量业务 API + 静态托管；WebUI 接后端 | 浏览器能建号、登录、记一笔，数据落库 |
| **P1** | Capacitor 壳（地址 + 账号登录、多地址回退、安全存储）；Android APK；CI 出未签名 IPA | 手机装上能登录能记账 |
| **P2** | 位置、单位换算、盘点修正、补货清单、成员与权限、自动备份 | 统计能按基准量加总 |
| **P3** | 自签 TLS（可选）、扫码录入（依赖 TLS）、从库存反推菜谱 | — |

P0 不依赖任何证书与设备，做完就能用浏览器访问——这是唯一能立刻开工的一段。

---

## 12. 风险与取舍

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 明文 HTTP | 多人共用 Wi-Fi 时密码可被嗅探 | 默认接受；敏感场景上自签 TLS（§4.4） |
| 单容器单进程 | 崩溃时网页与 App 同时不可用 | `restart: unless-stopped` + 健康检查 |
| SQLite 单写者 | 高并发写排队 | WAL + `busy_timeout=5000`；家用并发极低 |
| 忘记密码 | 无法登录 | 提供 `docker compose exec freshkeep node server/reset-password.js` 本地重置（需容器内权限） |
| 企业证书被吊销 | 已装 iOS App 打不开 | 数据在服务端，重签重装即恢复 |
| 误映射公网端口 | 暴露面骤增 | `ALLOW_CIDR` 兜底 + 部署清单里明确写"不映射" |
| NAS 单点故障 | 数据丢失 | 每日 `VACUUM INTO` + 建议再同步一份到另一台设备 |
