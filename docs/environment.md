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

## 5. 什么时候才真正需要 Docker / Xcode

| 工具 | 不需要它的工作 | 必须它的工作 |
| --- | --- | --- |
| Docker | 后端/前端开发、pytest、DDL 验证 | 验证 `docker compose up`、镜像构建、迁移自动执行 |
| Xcode | 全部后端与 Web 工作 | 本地出未签名 IPA（iOS 真机自签） |

两者缺失都不阻塞 M0~M8，只影响 M9（iOS 出包）与部署验证。

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
