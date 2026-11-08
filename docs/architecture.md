# 鲜度 FreshKeep · 自托管方案（v3：仅 Passkey 登录）

> **v3 相对 v2 的变更**
> 1. **认证只保留通行密钥（Passkey / WebAuthn）**：删除账号密码、"成员"与改密流程。
> 2. **新增硬前提：必须有域名 + HTTPS**——Passkey 的 RP ID 不能是 IP，且必须安全上下文。
>    **这一条推翻了"App 里填 IP 直连"的形态**，方案改为"填域名"，并在 §3.2 给出三条落地路径。
> 3. **网络层新增 Tailscale sidecar**：由它做 TLS 终结与证书自动续期，Node 继续跑 HTTP，公网零入口。
> 4. 数据库换成 `credentials` / `challenges` / `recovery_codes`，`users.pwd_hash` 删除。
> 5. 明文相关的 iOS ATS / Android cleartext 配置**全部不再需要**（因为强制 HTTPS）。

---

## 0. 一页结论

| 组件 | 选型 | 关键理由 |
| --- | --- | --- |
| 登录 | Passkey（WebAuthn，ES256，UV=required） | 你的要求；无密码、抗钓鱼、苹果设备原生 Face ID |
| 服务端验证 | **零依赖**：`node:crypto` + 自写 CBOR 解码 | 已实测跑通（§3.5） |
| 网络入口 | Tailscale sidecar → `https://<nas>.<tailnet>.ts.net` | 自动证书、仅 tailnet 内可达、无公网端口 |
| 应用 | Node 24 + SQLite + 静态 WebUI，单容器 | 与 v1/v2 一致 |
| 手机 App | Capacitor 壳：系统认证会话完成 passkey → code 换会话 Cookie | 绕开 WebView 的 WebAuthn 兼容性与 associated domains 依赖 |
| iOS 出包 | GitHub Actions 出未签名 IPA，你用长期证书自签 | 本机无 Xcode |

**一句话**：只有一条登录路径，就是通行密钥；只有一种地址，就是带证书的域名；数据只有一份，在 NAS 的 SQLite 里。

---

## 1. 边界

| 项 | 取值 |
| --- | --- |
| 网络可达 | 仅局域网 + 异地组网（Tailscale / ZeroTier）。**不映射公网端口，不做反代对外** |
| 认证 | 仅 Passkey。无密码、无账号、无"忘记密码" |
| 用户数 | 只有你一个（`users` 表保留一行 `owner`，为将来留位） |
| TLS | **强制**（Passkey 的前提，不是可选项） |
| 数据 | 单容器、SQLite 单文件、`/data` 卷 |

---

## 2. 架构

```
 iPhone / iPad / Mac                     家里/公司的电脑
 （Face ID 验通行密钥）                  （Safari/Chrome 验通行密钥）
        │                                        │
        └────────── Tailscale 隧道（加密） ───────┘
                            │
                https://<nas>.<tailnet>.ts.net   ← 证书由 Tailscale 自动签发/续期
                            │
              ┌─────────────┴──────────────┐
              │  sidecar 容器 ts           │  TLS 终结 :443 → 转发 127.0.0.1:8080
              └─────────────┬──────────────┘
                            │ (共享 network namespace)
              ┌─────────────┴──────────────────────────┐
              │  容器 freshkeep（Node 单进程）          │
              │   /            WebUI（SPA）             │
              │   /api/v1/auth/passkey/*  注册与登录    │
              │   中间件：ORIGIN 校验 → 会话 → 限流     │
              │            │                            │
              │            ▼                            │
              │   SQLite /data/freshkeep.db            │
              │   users / credentials / sessions        │
              │   items / logs / settings               │
              │   每日 VACUUM INTO /data/backups/*.db   │
              └─────────────────────────────────────────┘
```

Node 只管业务，TLS 与证书生命周期交给 sidecar——这是本方案最省心的分工，因为**证书要能自动续期**，
手写自签证书三个月后必然忘记，登录会突然全部失效。

---

## 3. Passkey 认证（核心）

### 3.1 先讲清硬约束（否则做出来用不了）

WebAuthn 有两条不可绕过的规则：

| 规则 | 含义 | 对本项目的后果 |
| --- | --- | --- |
| **RP ID 必须是域名** | 规范要求 RP ID 是有效域名，且是当前 origin 的可注册后缀；**IP 字面量不能当 RP ID** | `http://192.168.31.198:8080` 上**无法创建或使用 Passkey**，浏览器会直接抛 `SecurityError` |
| **必须是安全上下文** | 只有 `https://` 或 `localhost` 才暴露 `navigator.credentials` | 内网 HTTP 访问时 `credentials` 为 `undefined`，连 API 都调不到 |

所以"填服务器 IP + Passkey 登录"这两个要求在规范层面是互斥的。
**结论：地址必须是域名，全程 HTTPS。** 局域网内也一样——只是域名解析到内网地址而已，速度不受影响。

### 3.2 三条落地路径

| 路径 | 地址形态 | 证书 | 需要做什么 | 适用 |
| --- | --- | --- | --- | --- |
| **A. Tailscale sidecar（推荐）** | `https://nas-xxx.tail1234.ts.net` | 由 Tailscale 自动签发并续期（Let's Encrypt） | 装 Tailscale、开 HTTPS Certificates、加一个 sidecar 容器 | 局域网 + 外网都要用；不想碰证书 |
| B. 内网域名 + 自签 CA | `https://fk.home.arpa` | 自签 CA | 每台设备装 CA 并"完全信任"（iOS 要装描述文件 + 在"关于本机→证书信任设置"里打开） | 不装 Tailscale，只在局域网用 |
| C. 真实域名 + DNS-01 | `https://fk.example.com` → 内网 IP | Let's Encrypt（DNS 验证） | 有域名 + DNS API；路由器/内网 DNS 把该域名指到 192.168.31.198 | 已有域名，追求"浏览器完全无提示" |

**推荐 A 的理由**：证书自动续期（这条最重要，B 的自签证书到期会让所有设备同时登录失败）；
`*.ts.net` 域名在公网 DNS 里查不到、也连不上，天然满足"不开放公网"；局域网内 Tailscale 会走 P2P 直连，
延迟 1~3 ms，体验与直连 IP 相同。

> **代价**：手机和电脑都要常驻 Tailscale 客户端。这是本方案唯一的"额外依赖"，换来的是免证书运维。

### 3.3 首次注册（bootstrap）

Passkey-only 系统最大的工程问题是"第一条凭据从哪来"——没有任何登录手段，就不能自助注册。做法：

```bash
# 数据库里没有任何凭据时，容器启动会打印提示；在 NAS 上执行：
docker compose exec freshkeep node server/enroll.js
# 输出：
#   一次性注册链接（5 分钟内有效）：
#   https://nas-xxx.tail1234.ts.net/setup?t=7f3c9a2e...
```

打开该链接 → 浏览器弹出 Face ID / Touch ID → 录入通行密钥 → 完成。

要点：
- 链接里的 token 是**一次性**的，5 分钟过期，用掉即失效；存的是 SHA-256；
- 未注册时 `/` 只显示"未初始化"页面，**不暴露任何注册入口**（避免别人抢先注册）；
- 如果链接过期，再执行一次命令即可。

### 3.4 登录流程

```
① 浏览器 GET /                → 无 Cookie：跳 /login
② 页面 POST /api/v1/auth/passkey/login/options
   ← { challenge, rpId, allowCredentials:[...], userVerification:"required", timeout:60000 }
     （challenge 存服务端内存 Map，TTL 120s，单次消费）
③ 浏览器调 navigator.credentials.get(options)
   → Face ID / Touch ID → 返回 { id, rawId, response:{clientDataJSON, authenticatorData, signature} }
④ POST /api/v1/auth/passkey/login/verify { id, ...response }
   服务端：验 origin / challenge / rpIdHash / UV / 签名 → 通过
   ← Set-Cookie: fk_sid=<32B>; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=2592000
⑤ 跳回原页面（保留 ?next=）
```

注册流程同构，`type` 变成 `webauthn.create`，额外要解析 `attestationObject`（CBOR）拿到凭据公钥。

### 3.5 服务端验证：零依赖实现（已实测）

只用 `node:crypto` 与一个约 100 行的只读 CBOR 解码器，不引任何 npm 包：

```js
// server/webauthn.js 的核心判定
function verifyAssertion({ authData, clientDataJSON, signature, publicKey, rpId, origin, expectChallenge }) {
  const cd = JSON.parse(clientDataJSON);
  if (cd.type !== 'webauthn.get')                       throw new Error('type 错');
  if (cd.challenge !== expectChallenge)                 throw new Error('challenge 不匹配');
  if (cd.origin !== origin)                             throw new Error('origin 不匹配');

  const hash = crypto.createHash('sha256').update(rpId).digest();
  if (!crypto.timingSafeEqual(authData.subarray(0, 32), hash)) throw new Error('rpIdHash 不匹配');

  const flags = authData[32];
  if (!(flags & 0x01)) throw new Error('用户未到场');   // UP
  if (!(flags & 0x04)) throw new Error('未做用户验证');  // UV

  const cdHash = crypto.createHash('sha256').update(clientDataJSON).digest();
  const ok = crypto.verify('sha256', Buffer.concat([authData, cdHash]), publicKey, signature);
  if (!ok) throw new Error('签名验证失败');
  return { signCount: authData.readUInt32BE(33) };
}
```

**实测结果**（Node 22.22.2，模拟 authenticator 生成的 P-256 凭据）：

```
验证结果: { ok: true, up: true, uv: true, signCount: 7 }
challenge 被改 → 拦截 ✓
origin 被改   → 拦截 ✓
signature 被改 → 拦截 ✓
CBOR 解码 attestationObject: { fmt:'none', authDataLen:37, 消耗67字节 / 总长67 } ✓
```

三个细节：
- **ES256 签名是 DER 编码**，Node 的 `crypto.verify` 默认按 DER 解析，直接可用，不要转成 raw(r||s)。
- **Apple 平台的 `signCount` 恒为 0**（iCloud Keychain 不维护计数器），所以不能做"计数器必须递增"的严格校验，
  只在"新旧都非 0 且变小时"报警。
- `attestation` 类型设为 `none`：不验证厂商证明链，只取公钥。个人自用不需要硬件背书，也避免因
  Apple/Google 的 attestation 根证书更新而失效。

### 3.6 凭据管理与"别把自己锁在门外"

| 机制 | 做法 |
| --- | --- |
| 多设备 | 同一用户可注册多条凭据：iPhone、iPad、Mac、USB 安全密钥。iCloud Keychain 会跨设备同步，但同属一个生态，**建议至少再注册一个不同生态的**（如 YubiKey 或 Android 机） |
| 恢复码 | 初始化时生成 10 个一次性恢复码（`XXXX-XXXX`），只存 SHA-256，要求抄下来离线保存；全部凭据丢失时，可用任一恢复码走 `/recover` 重新注册凭据 |
| 凭据列表 | 设置页显示每条凭据的：设备名（`transports` + UA 推断）、创建时间、最后使用时间，可单独删除 |
| 吊销会话 | 与会话解耦：删凭据 = 以后不能登录；吊销会话 = 当前已登录的设备立刻掉线 |

**必须提前做的**：把 10 个恢复码打印/抄到纸上，或存进 1Password/Bitwarden 的离线备注。
Passkey 存在钥匙串里，删了钥匙串或换 Apple ID 就没了——这是这套方案唯一的"自伤风险"。

---

## 4. 数据库

### 4.1 表结构（v3 变化部分）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE users (
  id          TEXT PRIMARY KEY,
  username    TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- 'owner'，仅作显示
  display_name TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL
  -- 没有 pwd_hash：认证完全交给凭据表
);

-- 通行密钥凭据（一条 = 一台设备/一把钥匙）
CREATE TABLE credentials (
  id            TEXT PRIMARY KEY,      -- base64url(credentialId)
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  public_key    BLOB NOT NULL,         -- COSE 公钥原始字节
  alg           INTEGER NOT NULL DEFAULT -7,   -- -7 = ES256
  sign_count    INTEGER NOT NULL DEFAULT 0,
  transports    TEXT NOT NULL DEFAULT '',      -- 'internal,hybrid'
  aaguid        TEXT NOT NULL DEFAULT '',
  label         TEXT NOT NULL DEFAULT '',      -- '时雨的 iPhone'
  created_at    INTEGER NOT NULL,
  last_used_at  INTEGER,
  revoked_at    INTEGER
);
CREATE INDEX idx_cred_user ON credentials(user_id, revoked_at);

CREATE TABLE recovery_codes (
  code_hash  TEXT PRIMARY KEY,        -- SHA-256(恢复码)
  created_at INTEGER NOT NULL,
  used_at    INTEGER
);

CREATE TABLE sessions (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash   TEXT NOT NULL UNIQUE,
  credential_id TEXT,                 -- 用哪条凭据登录的，便于排查
  device_name  TEXT NOT NULL DEFAULT '',
  ip           TEXT NOT NULL DEFAULT '',
  user_agent   TEXT NOT NULL DEFAULT '',
  created_at   INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  revoked_at   INTEGER
);

CREATE TABLE auth_tokens (              -- 一次性：注册链接 / App 换取会话
  token_hash TEXT PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('enroll','app_exchange')),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at    INTEGER
);

CREATE TABLE login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT NOT NULL, ok INTEGER NOT NULL, at INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT ''
);
```

`challenges` 不落库：内存 `Map<challenge, {expiresAt, kind}>` + 每分钟清理。重启丢失只会让正在登录的人重试一次，
比多一张表更简单。

### 4.2 业务表保持不变

`items`（含 v2 的 `location` / `base_unit` / `base_factor` / `opened_at`）、`logs`（`use/restock/waste/adjust/opened` 五类 + `base_amount` + `op_id` 幂等）、`settings` 完全沿用 v2，
事务模板与幂等行为已在 SQLite 3.51.2 上实跑验证（库存 2 用 9 只扣到 0、空库存不写流水、重复 `op_id` 被唯一约束拦下）。

### 4.3 存储与迁移（借鉴自两个参考项目）

| 做法 | 来源 | 我们怎么用 |
| --- | --- | --- |
| SQLite 单文件 + `data` 目录可写即可运行 | grocy | `/data/freshkeep.db`，其余全在库里 |
| 版本变化自动迁移 | grocy | `PRAGMA user_version` 顺序执行迁移函数 |
| 显式迁移链（Alembic） | mealie | 迁移写成 `migrations/00X_*.sql`，按序执行，禁止跳版 |
| 在线备份不锁库 | 两者 | `VACUUM INTO`（不是 `cp`，WAL 下 `cp` 会拿到不一致快照） |
| 长期 API Token | mealie | `auth_tokens` 表 + 脚本可用的长期 token（P2） |

---

## 5. API（认证部分重写）

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/ping` | 否 | `{name,version,rpId,initialized,serverTime}`，App 用来验地址 |
| GET | `/setup?t=<token>` | 一次性 token | 注册页（仅首次） |
| POST | `/api/v1/auth/passkey/register/options` | 一次性 token | 返回 `PublicKeyCredentialCreationOptions` |
| POST | `/api/v1/auth/passkey/register/verify` | 一次性 token | 存凭据 + 生成恢复码 + 建会话 |
| POST | `/api/v1/auth/passkey/login/options` | 否 | 返回 `allowCredentials`（不含用户信息泄露） |
| POST | `/api/v1/auth/passkey/login/verify` | 否 | 验签成功 → 会话 Cookie |
| POST | `/api/v1/auth/recover` | 恢复码 | 校验恢复码 → 允许重新注册一条凭据 |
| POST | `/api/v1/auth/logout` | 是 | 删会话 |
| GET/DELETE | `/api/v1/credentials[/:id]` | 是 | 凭据列表 / 吊销 |
| GET/DELETE | `/api/v1/sessions[/:id]` | 是 | 已登录设备 / 吊销 |
| GET | `/api/v1/auth/app-exchange?code=` | 一次性 code | App 用系统浏览器登录后换会话 Cookie（§7.2） |
| — | 其余业务接口 | 是 | 与 v2 完全一致 |

错误码：`401` 未登录 / `403` origin 或网段不符 / `409` challenge 已消费 / `429` 限流。

---

## 6. WebUI 改造

- 新增 `login.html`（独立轻页面：一个按钮"用通行密钥登录" + 错误提示 + "从其他设备添加"引导），
  以及 `setup.html`（注册页）。主应用只在**已登录**时加载，避免把业务代码暴露给未认证访问。
- `js/store.js` 仍是"内存缓存 + 乐观更新 → 后台提交 → 失败回滚"，`app.js` 不改（与 v2 一致）。
- 401 处理：任何接口返回 401 → 清缓存 → 跳 `/login?next=<当前 hash>`；登录成功回原位。
- 前端不需要任何 WebAuthn 库：`navigator.credentials` 是浏览器原生 API，`base64url ↔ ArrayBuffer` 两行互转即可。

```js
// 前端就这么多
const b64 = a => btoa(String.fromCharCode(...new Uint8Array(a)))
  .replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const unb64 = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
```

---

## 7. 移动端 App

### 7.1 为什么不能在 WebView 里直接调 Passkey

| 平台 | 障碍 |
| --- | --- |
| iOS | WebView 里的 WebAuthn 需要 **associated domains**（`webcredentials:<域名>`）+ 服务端 AASA 文件 + **Team ID 匹配的 entitlement**。你用长期证书自签，重签过程会改写 entitlements，这条链路基本走不通 |
| Android | WebView 对 WebAuthn 的支持取决于系统 WebView 版本（Android 14 起才较完整）；Custom Tabs 反而稳定 |

**所以 App 不自己实现 passkey，而是借系统浏览器**——Safari / Chrome 对 passkey 是原生支持，与站点域名天然匹配。

### 7.2 登录链路（关键设计）

```
① App 首屏（本地页）：填服务器域名（https://nas-xxx.ts.net）+ [登录]
② App 打开系统认证会话 ASWebAuthenticationSession（Android 用 Custom Tabs）
      → https://<域名>/auth/app-start?device=iPhone
③ 系统浏览器里完成 passkey（Face ID）
      → 服务端生成一次性 code，302 到 freshkeep://auth?code=<code>
④ 会话窗口自动关闭，App 拿到 code
⑤ App 的 WebView 打开 https://<域名>/api/v1/auth/app-exchange?code=<code>
      → 服务端校验（60 秒、一次性）→ Set-Cookie → 302 到 /
⑥ 之后 WebView 与服务器同源，Cookie 自动携带，不需要注入 token、不需要 CORS
```

要点：
- 第 ⑤ 步是**用 WebView 自己发起的导航**，所以 Cookie 落在 WebView 的容器里——不需要 CapacitorCookies 手工写入，
  也不需要 `CapacitorHttp` 打补丁；这是整个链路里最省事的一处。
- `app_exchange` 的 code 只存 SHA-256、60 秒失效、用一次即废。
- App 需要注册自定义 URL scheme `freshkeep://`（Android 再配一个 App Link 更稳）。

### 7.3 域名代替 IP 之后的其他调整

| 项 | 变化 |
| --- | --- |
| 地址输入 | 填域名，不再填 IP；支持粘贴整条 URL（自动补 `https://`、去尾斜杠）；支持扫码导入 |
| 多地址回退 | 保留：`[tailnet 域名, 备用组网域名]`；**IP 不再作为候选**（能连通但无法登录，只会误导） |
| 连通性诊断 | `/api/v1/ping` 不通时提示"隧道未连接"，403 时提示"不在允许网段"，`initialized:false` 时提示"去 NAS 执行 enroll" |
| 本地网络权限 | 用 `*.ts.net` 域名时流量走 Tailscale，通常**不触发** iOS 的本地网络授权弹窗；若改用内网域名/IP，需要在 `Info.plist` 加 `NSLocalNetworkUsageDescription` 并授权 |
| ATS / cleartext | **全部不需要了**：全程 HTTPS，iOS 无需 `NSAllowsArbitraryLoads`，Android 也无需 `usesCleartextTraffic` |

---

## 8. 部署

### 8.1 docker-compose（含 TLS 终结）

```yaml
services:
  ts:
    image: tailscale/tailscale:latest
    container_name: freshkeep-ts
    hostname: nas-freshkeep
    restart: unless-stopped
    environment:
      TS_AUTHKEY: ${TS_AUTHKEY}          # 在 Tailscale 后台生成，建议用 ephemeral+tagged
      TS_STATE_DIR: /var/lib/tailscale
      TS_EXTRA_ARGS: --advertise-tags=tag:server
    volumes:
      - ./ts-state:/var/lib/tailscale
    ports:
      - "8080:8080"                       # 仅内网调试用，生产可删
    cap_add: [NET_ADMIN]

  freshkeep:
    build: .
    container_name: freshkeep
    restart: unless-stopped
    network_mode: "service:ts"            # 与 ts 共享网络，只监听 127.0.0.1
    depends_on: [ts]
    environment:
      TZ: Asia/Shanghai
      DATA_DIR: /data
      RP_ID: nas-freshkeep.tail1234.ts.net          # 必须与访问域名完全一致
      ORIGIN: https://nas-freshkeep.tail1234.ts.net # 同上，验证 clientDataJSON.origin
      TRUST_PROXY: "1"
    volumes:
      - ./data:/data
```

一次性设置（状态存在 `ts-state` 卷里，之后自动生效、证书自动续期）：

```bash
docker compose exec ts tailscale serve --bg --https=443 http://127.0.0.1:8080
```

前置条件：Tailscale 后台开启 **HTTPS Certificates**（DNS 页签里），否则 `tailscale serve` 拿不到证书。

**`RP_ID` 与 `ORIGIN` 必须和实际访问的域名逐字一致**——换域名等于所有凭据失效（因为 rpIdHash 变了），
这也是为什么域名一旦定下就不要改。

### 8.2 首次部署

```bash
mkdir -p /vol1/docker/freshkeep/{data,ts-state}
cd /vol1/docker/freshkeep && git clone git@github.com:0shiyu0/freshkeep.git .
echo "TS_AUTHKEY=tskey-auth-xxxx" > .env
docker compose up -d --build
docker compose exec ts tailscale serve --bg --https=443 http://127.0.0.1:8080
docker compose exec freshkeep node server/enroll.js   # 拿一次性注册链接
```

### 8.3 备份与恢复

- 每日 03:00 `VACUUM INTO /data/backups/freshkeep-<stamp>.db`，保留 14 份；
- 恢复：停容器 → 覆盖 `freshkeep.db` → **删掉 `-wal`、`-shm`** → 启动；
- **凭据表也在这份备份里**：恢复后 passkey 照常可用（凭据公钥在库里，私钥在设备钥匙串里，两者分离）。

---

## 9. 发布（与 v2 相同，一处变化）

Android：`keytool` 生成 keystore → `assembleRelease` → APK 放 NAS 下载。覆盖升级要求同签名 + `versionCode` 递增。

iOS：GitHub Actions `macos-14` 上 `xcodebuild archive` 加 `CODE_SIGNING_ALLOWED=NO` → 组 `Payload/App.app` → 压成**未签名 IPA** → 你用长期证书重签（Sideloadly / ESign，bundle id 用通配符）→ 信任证书 → iOS 16+ 开开发者模式。

**变化**：因为不再需要 associated domains 与 ATS 例外，重签只需处理 `application-identifier` 与 `keychain-access-groups`，
失败率比 v2 低。自定义 URL scheme `freshkeep://` 需要在 `Info.plist` 的 `CFBundleURLTypes` 里声明，重签不影响。

---

## 10. 分期

| 阶段 | 内容 | 完成标志 |
| --- | --- | --- |
| **P0** | 服务端：SQLite + Passkey 注册/登录 + 会话 + 业务 API + 静态托管；Tailscale sidecar 跑通 | 浏览器用 Face ID 登录并记一笔 |
| **P1** | Capacitor 壳：域名输入 + 系统认证会话 + code 换会话；Android APK；CI 出未签名 IPA | 手机装上能登录能记账 |
| **P2** | 恢复码、凭据管理页、位置、单位换算、盘点修正、补货清单、自动备份 | 运维闭环 |
| **P3** | 硬件密钥支持、长期 API Token（快捷指令/Home Assistant）、从库存反推菜谱 | — |

---

## 11. 风险与取舍

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **钥匙串丢失 → 锁死** | 无法登录 | 恢复码（必做）+ 至少两条不同生态的凭据 |
| 域名变更 | 所有凭据失效（rpIdHash 变了） | 域名一次定死；换域名要走"恢复码重新注册"流程 |
| Tailscale 服务不可用 | 无法访问（含局域网） | 保留局域网直连端口作为**应急通道**：只读页面 + 明确提示"需重新登录请修好隧道" |
| 证书过期 | 同上 | 选路径 A（自动续期）；选 B 必须在日历里设续期提醒 |
| 自签 iOS 重签失败 | App 装不上 | 去掉 associated domains / ATS 后已大幅降低失败面 |
| 单容器单进程 | 崩溃时全站不可用 | `restart: unless-stopped` + 健康检查 |
| SQLite 单写者 | 并发写排队 | WAL + `busy_timeout=5000`；个人使用并发极低 |
| NAS 单点故障 | 数据丢失 | 每日 `VACUUM INTO` + 建议再同步一份到另一台设备 |

> **关于"局域网直连 IP"这件事的最终结论**：技术上可以保留 `http://<ip>:8080` 作为**只读诊断入口**
> （能看到"服务在跑、隧道断了"），但不能登录——因为 Passkey 在非安全上下文里根本不可用。
> 想彻底摆脱 Tailscale 依赖，只能走路径 B/C（内网域名 + 证书）。
