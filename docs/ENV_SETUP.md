# 环境搭建与验证手册

> 目标：把「本机跑不起来」变成「一条命令能验证」。
> 每一项都给出**命令 → 预期输出 → 验证方式**，照着做能自证成功与否。

---

## 0. 三个问题的实测结论

| 问题 | 实测证据 | 结论 |
| --- | --- | --- |
| PostgreSQL 装不上 | `brew install` 在 agent 沙箱里报 `sandbox-exec: sandbox_apply: Operation not permitted`（Homebrew 解包时需要沙箱，被上层沙箱挡住） | **不是权限或系统问题**，在你自己终端里执行即可；或改用 Docker / PGlite |
| pip 极慢 | 同机同网：默认源 `6 分 33 秒`；清华镜像 + `--only-binary` `24.7 秒`；uv `1.3 秒` | 瓶颈是 **pypi.org 的跨境延迟**，不是编译 |
| npm | `npm view vue version` < 1s，`npm i @electric-sql/pglite` 40s | 无需处理；如遇慢可换 npmmirror |

---

## 1. 一次性准备（推荐顺序）

```bash
# 在仓库根目录
./scripts/dev-setup.sh      # 装后端依赖 + 前端依赖 + 构建 + 建库 + 跑 DDL + 跑自检
./scripts/verify-env.sh     # 逐项体检，输出 ✓ / ! / ✗
```

`dev-setup.sh` 是幂等的，重复执行不会重复下载。

---

## 2. PostgreSQL

### 路径 A · 本机 Homebrew（推荐，日常开发）

**在你自己打开的系统终端里执行**（不是 agent 会话）：

```bash
brew install postgresql@16
```

**预期输出**：末尾出现 `==> Summary` 与 `🍺  /opt/homebrew/Cellar/postgresql@16/16.x: 3,xxx files, xxxMB`。

```bash
brew services start postgresql@16
```

**预期输出**：`==> Successfully started postgresql@16 (label: homebrew.mxcl.postgresql@16)`

**验证**：

```bash
psql --version          # 期望：psql (PostgreSQL) 16.x
pg_isready              # 期望：/tmp:5432 - accepting connections
```

如果 `psql` 说找不到命令，把它加进 PATH：

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc && exec zsh
```

**建库并建表**：

```bash
createdb freshkeep                                   # 无输出即成功
psql -d freshkeep -f database/001_init.sql           # 期望：BEGIN … 一串 CREATE … COMMIT
psql -d freshkeep -f database/002_acceptance_check.sql 2>&1 | grep NOTICE
```

**预期验收输出**：

```
NOTICE:  用例1（批次成本）通过：成本 10.80 / 批次1 剩 200g·7.20 / 合计 42.20
NOTICE:  用例3（营养快照）通过：300g × 165kcal/100g = 495 kcal
NOTICE:  用例2（FEFO）通过：A 清零、B 剩 900g；对账三个 diff 均为 0
NOTICE:  约束通过：remaining_weight 负值被 CHECK 拒绝
NOTICE:  约束通过：(transaction_id, batch_id) 重复分配被拒
NOTICE:  约束通过：consume 的正 delta 被 ck_tx_sign 拒绝
NOTICE:  约束通过：营养快照的外键拒绝孤儿记录
NOTICE:  === 全部验收用例通过 ===
```

**表数验证**：

```bash
psql -d freshkeep -tAc "select count(*) from information_schema.tables
  where table_schema='public' and table_type='BASE TABLE'"     # 期望：25
```

**本地连接串**（写进 `backend/.env` 或直接 export）：

```bash
export DATABASE_URL="postgresql+psycopg://$(whoami)@127.0.0.1:5432/freshkeep"
```

> Homebrew 版 PG 的默认超级用户是你的 macOS 用户名，没有密码。容器版才是 `freshkeep/密码`。

---

### 路径 B · Docker（若已装 Docker Desktop）

```bash
docker run -d --name fk-pg \
  -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=freshkeep \
  -p 5432:5432 postgres:16-alpine
```

**验证**：

```bash
docker exec fk-pg pg_isready -U postgres          # 期望：accepting connections
docker exec -i fk-pg psql -U postgres -d freshkeep -f - < database/001_init.sql
docker exec -i fk-pg psql -U postgres -d freshkeep -f - < database/002_acceptance_check.sql
```

连接串：`postgresql+psycopg://postgres:dev@127.0.0.1:5432/freshkeep`

> 这条路**同时验证了 compose 要用的镜像版本**，也是补验 `pg_trgm` 的唯一途径（见 §2.4）。

---

### 路径 C · 没有 PG 也能验证 SQL（PGlite）

PGlite 是 PostgreSQL 16 内核编译成的 WASM，跑在 Node 里，无需安装任何数据库：

```bash
npm i --no-save @electric-sql/pglite
node scripts/verify-db.mjs
```

**预期输出**：

```
✅ DDL 执行成功：25 张表 / 2 个视图
✅ 002 验收脚本：全部断言通过
   消耗 300g → 成本 10.80；批次 B1 剩 200g·7.20，B2 剩 1000g·35.00；合计 42.20
   营养快照 495.0000 kcal；对账差异 B1 0/0，B2 0/0
```

用途：改 DDL 后快速回归，不依赖本机数据库。**注意它不带 `pg_trgm`**，脚本会自动剔除该扩展与两条 GIN 索引。

---

### 2.4 唯一必须用真 PG 补验的点

`pg_trgm` 扩展与两条 GIN 索引（中文模糊搜索、拼音搜索）在 PGlite 上不可用。
在路径 A 或 B 的库里跑一次即可确认：

```bash
psql -d freshkeep -c "create extension if not exists pg_trgm;"
psql -d freshkeep -c "\d+ ingredients" | grep trgm      # 期望看到两条 gin 索引
psql -d freshkeep -c "select name from ingredients where name ilike '%牛%';"   # 期望能命中
```

---

## 3. pip 加速

### 方案 A · 用 uv（最快，推荐）

```bash
python3 -m pip install uv          # 一次性
cd backend
uv pip install --python .venv/bin/python \
  -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

**实测**：冷启动 1.3 秒（uv + 镜像），uv + 默认源 69 秒，pip + 默认源 393 秒。
**验证**：`.venv/bin/python -c "import fastapi, sqlalchemy; print('ok')"`

### 方案 B · pip + 镜像 + 仅二进制

```bash
cd backend
.venv/bin/pip install --only-binary=:all: \
  -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

**实测**：24.7 秒。
**说明**：`--only-binary=:all:` 强制用预编译轮子，避免任何 sdist 编译；若将来某个包没有轮子，
去掉该参数即可（会退化为源码安装）。

### 方案 C · 持久化镜像（一次配置，全局生效）

```bash
mkdir -p ~/.config/pip
cat > ~/.config/pip/pip.conf <<'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
EOF
pip config list        # 验证：global.index-url=…
```

> macOS 若 `~/.config/pip` 不生效，用 `~/Library/Application Support/pip/pip.conf`（同内容）。

### Docker 构建也加速

`backend/Dockerfile` 已支持构建参数：

```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

默认值就是清华源；海外网络可传 `https://pypi.org/simple` 覆盖。

---

## 4. npm（仅在慢时处理）

```bash
npm config set registry https://registry.npmmirror.com
npm config get registry        # 验证
```

---

## 5. Docker 与 Xcode（2026-11-09 实测）

### 5.1 Docker：已可用，但 CLI 原本不在 PATH

| 项 | 值 |
| --- | --- |
| Docker Desktop | 4.98.0 |
| 引擎 / 客户端 | 29.9.2（client = server） |
| Compose | v5.6.1（内置插件） |
| 守护进程 | 运行中（`com.docker.backend`，10 CPU / 8 GB 分配给 VM） |
| 实际可用性 | `docker run hello-world` 成功；本项目 `docker compose up -d --build` 37 秒完成，两容器 healthy |

**当时遇到的问题**：`docker: command not found`。原因不是没装，而是 CLI 只在
`/Applications/Docker.app/Contents/Resources/bin/` 与 `~/.docker/bin/`（后者是指向 app 的符号链接），
两者都不在 `PATH`，也没有 `/usr/local/bin/docker`。

**修复**（已写入 `~/.zshrc`，删掉那三行即可撤销）：

```sh
if [ -d "$HOME/.docker/bin" ]; then export PATH="$HOME/.docker/bin:$PATH"; fi
```

验证：新开窗口执行 `which docker && docker --version` → 应输出 `~/.docker/bin/docker` 与版本号。

**其他注意点**：

- 根卷（`/System/Volumes/Data`）只剩 **16 GiB**，`docker compose build` 与镜像会占 1~3 GB，空间偏紧。
- `docker compose config` 会因缺少 `.env` 的 `POSTGRES_PASSWORD` 报错，这是设计如此：
  先 `cp .env.example .env` 并填随机密码（`openssl rand -base64 24`）。

### 5.2 Xcode：已可用，装在外接盘，没有模拟器运行时

| 项 | 值 |
| --- | --- |
| 版本 | Xcode **27.2**（Build 27B52） |
| 实际路径 | `/Volumes/移动硬盘/XcodeApps/Xcode.app` |
| `xcode-select -p` | `/Volumes/移动硬盘/XcodeApps/Xcode.app/Contents/Developer` ✅ |
| `/Applications/Xcode.app` | 指向外接盘的**符号链接**（兼容只认该路径的工具） |
| 首次启动 | `xcodebuild -checkFirstLaunchStatus` 退出码 0（已完成） |
| SDK | macOS.sdk、iPhoneOS27.2.sdk、iPhoneSimulator27.2.sdk |
| 工具链 | `xcrun swiftc` 编译并运行成功（3.8 秒） |
| 代码签名 | `Authority=Software Signing / Apple Code Signing Certification Authority`（正版） |
| 外接卷格式 | APFS，挂载参数 `local, nodev, nosuid, journaled, noowners` |
| 隔离属性 | 无 `com.apple.quarantine`（只有 `com.apple.macl` / `provenance`，不影响运行） |

**结论：不存在权限或授权问题。** 三点依据：

1. `noowners` 表示忽略磁盘上的属主记录，一律按当前用户解释 → 不会有"文件属于别人"的读写拒绝；
2. 没有 `noexec`，可执行权限正常 → `swiftc` 产物与 Xcode 内部二进制都能跑（已实测）；
3. 没有 quarantine → 不会被 Gatekeeper 拦；`codesign` 验签正常。

**真正需要注意的两个风险**：

| 风险 | 后果 | 应对 |
| --- | --- | --- |
| 外接盘未挂载/被拔出 | `xcodebuild`、`xcrun` 全部失效，`/Applications/Xcode.app` 变悬空链接 | 构建前先 `xcode-select -p` 确认路径可访问；不要在做 CI/出包时拔盘 |
| **没有 iOS 模拟器运行时**（`xcrun simctl list runtimes` 为空，Disk Images 0） | 不能 `npx cap run ios` 跑模拟器 | 根卷只剩 16 GiB，而 iOS runtime 约 7~9 GB。**建议直接用真机**（`xcodebuild` 出未签名 IPA + 自签）；确实要模拟器就先腾空间再 `xcodebuild -downloadPlatform iOS` |

> 附：模拟器数据默认在 `~/Library/Developer/CoreSimulator`（内建盘），不占外接盘；
> DerivedData 同理在 `~/Library/Developer/Xcode/DerivedData`，也不在外接盘。

---

## 6. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `psql: command not found` | brew 的 keg-only 未进 PATH | 见 §2 路径 A 的 PATH 追加命令 |
| `createdb: could not connect` | 服务没起 | `brew services start postgresql@16`；`pg_isready` 确认 |
| `role "root" does not exist` | 用了别人的用户名 | 用 `$(whoami)`；或 `createuser -s $(whoami)` |
| `psql -f` 报 `relation already exists` | 重复执行 DDL | 重建库：`dropdb freshkeep && createdb freshkeep` |
| `pg_trgm` 创建失败 | 用了精简版 PG 镜像 | 换 `postgres:16-alpine` 官方镜像 |
| pip 仍慢 | 未走镜像 | `pip config list` 确认 index-url；或改用 uv |
| `npm ci` 报 lock 不一致 | 没有 `package-lock.json` | 首次用 `npm install` 生成并提交 |
