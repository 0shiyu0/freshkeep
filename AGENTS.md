# AGENTS.md · 项目规则

> 本文件是**所有协作者（人或 AI）动工前必须先读的约定**。与本文冲突的实现视为缺陷。
> 项目：鲜度 FreshKeep —— 家庭食材库存与营养管理，NAS 私有部署，原生 App + Web。

---

## 1. 唯一真相来源（文档地图）

**五份文档 + 本文件**构成自足体系：只读它们就能恢复开发状态（路径按 2026-11-08 重整后的结构）。

| 文件 | 回答什么问题 | 何时读 | 必读 |
| --- | --- | --- | --- |
| `AGENTS.md` | 我该遵守什么规则 | 每次动工前 | ✅ 强制 |
| `docs/PRD.md` | 产品要做什么、不做什么、验收数字是多少 | 改需求或写业务逻辑前 | ✅ 强制 |
| `docs/ARCHITECTURE.md` | 系统怎么搭：分层、认证、数据模型、API、核心算法 | 设计实现方案时 | ✅ 强制 |
| `docs/DEVELOPMENT_PLAN.md` | 分几个阶段、每阶段任务与完成判据 | 排期与验收时 | ✅ 强制 |
| `docs/PROJECT_STATUS.md` | 现在做到哪、有什么已知问题、下一步是什么 | 每次接手时 | ✅ 强制 |
| `docs/CHANGELOG.md` | 最近改了什么、数据库动过什么 | 排查回归时 | 建议 |

**详细附录**（不重复上述内容，只在需要字段级/接口级细节时查）：

| 文件 | 内容 |
| --- | --- |
| `database/001_init.sql` | **DDL 唯一真相**：25 表 + 2 视图 + 索引/约束/触发器 |
| `database/002_acceptance_check.sql` | 数据库侧验收断言（PRD 三条用例 + 四类约束反向验证） |
| `docs/database.md` | 逐字段说明、索引理由、与 PRD 的差异 |
| `docs/er-diagram.md` | ER 图（mermaid）、关系清单、状态机 |
| `docs/api.md` | 完整接口契约、请求响应样例、错误码 |
| `docs/final-plan.md` | 8 处冲突的论证过程（决策溯源） |
| `docs/environment.md` | 环境搭建与验证手册（PG 安装、pip 加速、排障） |
| `docs/state/README.md` | 状态留痕机制：哪些自动、哪些手动 |

**归档文档**（`docs/archive/`，仅作历史参考，不得作为实现依据）：
`architecture-v3-passkey.md`、`implementation-plan-v4-node.md`、`prd-alignment.md`。

**冲突处理顺序**：`AGENTS.md` > `docs/ARCHITECTURE.md` / `docs/PRD.md` > 其余 `docs/*` > `docs/archive/*`。


---

## 2. 目录约定

```
backend/app/{core,db,models,schemas,services,api/v1,tasks}   # 后端，按职责分层
backend/alembic/versions/                                     # 迁移（只登记版本，不写 DDL）
backend/tests/{unit,api,acceptance}/                          # 单测、接口测试、验收用例
frontend/src/{views,components,stores,api,router,styles}/      # 前端
frontend/{android,ios}/                                       # Capacitor 原生工程（提交入库）
database/                                                     # DDL 与自检脚本
deploy/                                                       # 部署脚本、备份脚本、NAS 手册
docs/                                                         # 文档
```

**分层铁律**：`api/v1/*.py`（HTTP 层）→ `services/*.py`（业务）→ `models/`（ORM）。
**路由器里不许写业务逻辑**，只做参数校验、调用 service、包装响应。

---

## 3. 技术栈（不得擅自变更主版本）

| 层 | 组件 | 版本 |
| --- | --- | --- |
| 后端 | Python / FastAPI / SQLAlchemy / Pydantic / Alembic / psycopg | 3.12+ / 0.162 / 2.1 / 2.14 / 1.20 / 3.3 |
| 数据库 | PostgreSQL | 16 |
| 前端 | Vue / Vite / Pinia / Naive UI / ECharts | 3.5 / 8.3 / 4.1 / 2.45 / 6.1 |
| 移动壳 | Capacitor | 8.6 |

新增依赖必须在 `final-plan.md` §6 的技术栈表里先登记，说明用途与替代方案。

---

## 4. 后端编码规则

### 4.1 数值（最容易出事的一条）

- 金额、重量、数量、营养值**全程 `Decimal`**，禁止 `float` 参与任何计算或比较。
- 除法一律 `Decimal.quantize` 到目标精度：金额 `0.01`，重量/数量 `0.001`，营养 `0.0001`。
- JSON 序列化时**输出字符串**（`"10.80"`），不要输出 number。
- 禁止 `round()` 处理 Decimal（用 `quantize`）；禁止 `==` 直接比较两个浮点来源的数。

### 4.2 库存写入

任何会改变库存的操作必须：

1. 在**一个事务**内完成；
2. 写一条 `inventory_transactions`；
3. 为它涉及的每个批次写一条 `transaction_allocations`；
4. 同步更新 `batches.remaining_*` 缓存；
5. 断言 `Σ allocations == transaction.delta`，不等则回滚。

**禁止**：直接 `UPDATE batches SET remaining_*` 而不写流水（唯一例外是对账修复任务，且必须写 `audit_logs`）。

### 4.3 FEFO 与并发

- 取批次必须 `SELECT … ORDER BY expiry_date NULLS LAST, purchase_date, id` + `WITH FOR UPDATE`。
- 批次的加锁顺序固定按 `expiry_date` 升序，避免多事务交叉死锁。
- 库存不足直接抛 `InsufficientStock`，**不做部分成功**。

### 4.4 幂等

所有库存写接口必须支持 `Idempotency-Key`：同 key 同 body 返回原响应，同 key 不同 body 返回 `DUPLICATE_REQUEST`。
实现走 `idempotency_keys` 表，不要用内存缓存（多 worker 下失效）。

### 4.5 状态迁移

`batches.status`、`consumption_records.status`、`shopping_lists.status`、`notifications.status`
只能通过 `services/*/state.py` 里的迁移函数修改，禁止在 router 或 repo 里直接赋值。

### 4.6 时间

- 数据库存 UTC（`timestamptz`）。
- 业务"哪一天"按 `Asia/Shanghai` 计算（临期天数、统计分组边界）。
- 不要用 `datetime.now()`（无时区），用 `datetime.now(timezone.utc)`；业务日期用统一的 `biz_today()` 工具函数。

---

## 5. 数据库规则

- **改表只改 `database/001_init.sql`**，Alembic 迁移仅登记版本号（`op.execute` 引用同一份 DDL 的分段），不允许出现第二份手写 DDL。
- 命名：表用复数 snake_case；索引 `ix_`、唯一索引 `ux_`、约束 `ck_`、视图 `v_`。
- 外键一律显式写 `ON DELETE`：历史表用 `RESTRICT`，从属表（条码/营养快照/清单项/菜谱项）用 `CASCADE`。
- 新增字段必须同步更新：`001_init.sql` → `docs/database.md` → `docs/er-diagram.md` → 对应 Pydantic schema。
- 枚举一律 `text + CHECK`，不用 PG ENUM（便于追加取值）。
- 金额 `NUMERIC(14,2)`、重量/数量 `NUMERIC(14,3)`、营养 `NUMERIC(14,4)`，不得改精度。

---

## 6. 前端规则

- 数值以**字符串**接收，展示原样；需要计算（图表求和）时转 `Number` 并只在展示层使用，不回写。
- 所有请求走 `src/api/` 的统一 client（自动带凭据、统一错误提示、401 跳配对页）。
- 状态放 Pinia，组件不直接 `fetch`。
- 颜色/间距用 CSS 变量，不写魔法值。
- 页面必须处理三态：加载中、空数据、出错（空数据要给出"下一步动作"）。

---

## 7. 测试规则

| 层级 | 位置 | 要求 |
| --- | --- | --- |
| 单元 | `tests/unit/` | 纯函数（FEFO、成本分摊、双计量换算、营养计算）必须有 pytest 用例 |
| 接口 | `tests/api/` | 每个路由至少一条成功 + 一条失败用例 |
| 验收 | `tests/acceptance/` | PRD §11 的 9 条，数字断言到分/卡，**必须全绿才算 M 阶段完成** |
| 数据库 | `database/002_acceptance_check.sql` | 在真库上验证约束与视图；改动 DDL 后必须重跑 |

本地准备与校验（一条命令，幂等）：

```bash
./scripts/dev-setup.sh    # 装依赖 + 构建前端 + 建库 + 跑 DDL + 跑自检
./scripts/verify-env.sh   # 逐项体检，输出 ✓ / ! / ✗
```

没有本机 PostgreSQL 时，用 PGlite 验证 SQL（不装任何数据库）：

```bash
npm i --no-save @electric-sql/pglite && node scripts/verify-db.mjs
```

`pip` 必须走镜像或 uv（默认源在本机实测要 6 分钟，镜像 25 秒，uv 1.3 秒），
细节与排障见 `docs/environment.md`。禁止用 SQLite 跑测试（无 NUMERIC、无行锁，会掩盖真实缺陷）；
禁止 mock 掉数据库做"集成测试"。

---

## 8. 提交规范

```
<type>(<scope>): <subject>

type: feat | fix | docs | refactor | test | chore | perf
scope: api | db | web | app | deploy | docs
```

示例：`feat(api): 实现 FEFO 消耗与成本分摊`

一个提交只做一件事；**DDL 变更必须单独提交**，提交信息带 `db:` 前缀并说明是否需要重建库。

---

## 9. 禁止事项

1. 禁止在业务代码里用 `float` 处理金额/重量。
2. 禁止绕过 service 层直接改 `batches.remaining_*`。
3. 禁止删除历史流水/消耗记录（撤销用 `reverse`）。
4. 禁止把长期令牌放 `localStorage`（Web 用 HttpOnly Cookie，App 用 Keychain/Keystore）。
5. 禁止在接口层拼接 SQL 字符串（一律 SQLAlchemy 参数化）。
6. 禁止提交 `.env`、`keystore`、`*.p12`、`*.mobileprovision`。
7. 禁止在未更新文档的情况下改字段/接口。
8. 禁止引入技术栈表以外的重依赖（如 ORM 替换、UI 框架替换）。

---

## 10. 阶段与验收

阶段划分见 `final-plan.md` §13（M0~M10）。每个 M 阶段的完成定义：

1. 对应接口/页面可用；
2. 单测与接口测试通过；
3. 相关文档已同步；
4. 若是 M4/M5/M6，`tests/acceptance/` 对应用例转绿；
5. 本地 `docker compose up` 能起（M0 起生效）。

---

## 11. AI 协作约定

- 动工前先读本文件与 `final-plan.md`，不要凭上下文记忆推断业务规则。
- 改动跨 3 个以上文件时，先给出改动清单再动手。
- 不确定的业务规则，按"最保守 + 可追溯"的方案实现，并在代码注释标注 `# ASSUMPTION:`，同时补进 `PRD.md` §8 已决策表下方的"待确认"小节。
- 不擅自升级主版本依赖、不改技术栈、不改验收数字。

---

## 12. 上下文管理与开发状态持久化

> 这一节解决一个问题：**会话被压缩、换人接手、或隔几天回来时，不能靠记忆，只能靠文件与数据库的客观状态。**
> 违反本节造成的典型后果：功能被标为"已完成"但代码没有；数据库手工改过但没有迁移记录；重复实现已有逻辑。

### 12.1 开发前必读（硬性，无条件）

按顺序读，缺一不可：

```
AGENTS.md → docs/PRD.md → docs/ARCHITECTURE.md → docs/DEVELOPMENT_PLAN.md → docs/PROJECT_STATUS.md
```

然后跑一次检查，把"文档说的"与"实际是什么"对齐：

```bash
./scripts/session-start.sh
```

它输出五块：必读文档行数、Git 工作区与最近提交、数据库迁移版本与表数、测试与构建结果、文档内链检查。

**必须自己核对的三件事**（不能只看文档）：

| 核对项 | 命令 | 判据 |
| --- | --- | --- |
| 代码状态 | `git status` / `git diff` / `git stash list` | 有无未提交改动、有无藏着没说的 WIP |
| Git 状态 | `git log -5 --stat` / `git rev-list --count @{u}..HEAD` | 最近做了什么、有没有没推的提交 |
| 数据库状态 | `alembic current` + 表数查询 | 版本号是否与 `database/001_init.sql` 一致、表数是否 25 |

> **禁止仅凭对话历史判断项目状态。** 对话可能被压缩、被总结、甚至被误述；
> 判断"某功能是否完成"的唯一依据是：**代码在 + 测试过 + 文档已更新**，三者一致。
> 三者不一致时，先纠正文档，再写代码。

### 12.2 每个独立功能完成后的记录义务

一个"独立功能"= 一次可验证的、有明确输入输出的增量（例：`POST /ingredients` 能建档、FEFO 分配能扣对批次）。

完成后必须更新 `docs/PROJECT_STATUS.md`，至少包含：

1. **功能名与验收方式**（跑什么命令、期望什么输出）
2. **涉及的架构决策**（若引入了新表/新依赖/新分层，写进 `docs/ARCHITECTURE.md` 的 ADR 表）
3. **数据库变更**（DDL 变了什么、迁移版本号、是否已备份）
4. **测试结果**（贴真实输出，不是"应该没问题"）
5. **失败原因**（调试过程中踩过的坑与结论）
6. **遗留问题**（做不到的、绕过的、待定的）

三条红线：

- **不得把未验证的功能标记为已完成**。"完成"的门槛：自动化测试通过 + 至少一次真实调用验证（curl 或界面操作）+ 文档已更新。
- **不得擅自覆盖既定业务规则**。要改 `docs/PRD.md` 里的规则（尤其是验收数字），必须先在 PRD 里写出 diff 与影响面，得到确认后才动代码。
- **不得删除或跳过既有测试**。测试失败要先判断是实现错还是测试错，改测试需要说明理由。

### 12.3 每次任务结束前的收尾清单（八项，缺一不可）

在 `docs/PROJECT_STATUS.md` 与最终回复里都要能回答：

| # | 项 | 要求 |
| --- | --- | --- |
| 1 | 当前阶段与任务 | 对应 `docs/DEVELOPMENT_PLAN.md` 的哪个 M |
| 2 | 已完成功能 | 每条附验证方式 |
| 3 | 修改和新增文件 | 按目录分组列出 |
| 4 | 数据库迁移情况 | 版本号、DDL 变更、备份路径；无变更也要写"无" |
| 5 | 已执行测试及结果 | 原始输出摘要（如 `4 passed`、验收 8 条 NOTICE） |
| 6 | 现存问题 | 编号 + 影响 + 处置 |
| 7 | 下一步建议 | 具体到可执行动作 |
| 8 | 未提交或未完成的改动 | **必须明说**，不许悄悄留着；用 `git status` 佐证 |

### 12.4 上下文压缩 / 新会话时的恢复流程

```
① 重读五份文档（§12.1）
② git log -5 --stat；git status；git stash list；git rev-list --count @{u}..HEAD
③ alembic current；表数；若有本地库，跑一次 database/002_acceptance_check.sql
④ 对照 docs/PROJECT_STATUS.md 的"未完成"清单与实际代码，逐条确认
⑤ 发现文档与实际不一致 → 先改文档再继续（把偏差写进 CHANGELOG 的"修复"小节）
⑥ 确认一致后再动手，并在回复里说明"依据哪几份文件判断的当前状态"
```

### 12.5 核心逻辑保护

以下五块**必须**有自动化测试，且不得在测试未覆盖的情况下改动：

| 核心逻辑 | 测试位置 | 现状 |
| --- | --- | --- |
| 数据库迁移（DDL 可执行、表数正确） | `database/002_acceptance_check.sql` + CI | ✅ 已有 |
| 库存流水（唯一写入口、符号约束） | `database/002` 的约束反向验证 | ✅ 已有 |
| 批次分配（`transaction_allocations` 与余额一致） | `database/002` 的对账断言 | ✅ 已有 |
| 成本核算（分摊 + 尾差 + 精度） | `database/002` 的 10.80 / 42.20 | ✅ 已有 |
| 营养快照（冻结、不随档案变化） | `database/002` 的 495 kcal | ✅ 已有 |

后续这些逻辑搬到 Python 后，测试要**同步平移**到 `backend/tests/acceptance/`，不得只剩 SQL 断言。

改核心逻辑的固定动作：

1. 先加/改测试，**看到它红**（证明测试有效）；
2. 再改实现；
3. 跑绿，并在提交信息里贴输出；
4. 若改变了行为，先改 `docs/PRD.md` 并说明影响面。

**未经确认不得做的事**：重构库存/成本/营养的核心算法；改验收数字；改表的主键或精度；把 `Decimal` 换成 `float`；绕过 `services` 层直接改余额。

### 12.6 规则与执行者对照（哪条真自动）

| 规则 | 执行者 | 触发点 | 真自动？ |
| --- | --- | --- | --- |
| 提交前跑测试、查机密、查文档同步、查浮点误用 | `.githooks/pre-commit` | `git commit` | ✅ |
| 提交后留痕（时间/hash/标题/影响域） | `.githooks/post-commit` → `docs/state/commits.log` | `git commit` | ✅ |
| 推送前跑全量测试 + 文档检查 | `.githooks/pre-push` | `git push` | ✅ |
| 远端跑 pytest + 真 PG 迁移 + 验收用例 + 前端构建 | `.github/workflows/ci.yml` | push / PR | ✅ |
| 迁移前备份并在失败时给回滚点 | `scripts/migrate-safe.sh` | 人主动执行 | ⚠️ 半自动 |
| 会话开始时核对状态 | `scripts/session-start.sh` | 人/agent 主动执行 | ⚠️ 半自动 |
| 状态快照（Git/迁移/测试/构建） | `scripts/status-snapshot.sh` | 手动或任务末尾 | ⚠️ 半自动 |
| 功能完成后的文字记录 | 人 / agent 写 `docs/PROJECT_STATUS.md` | 功能完成时 | ❌ 手动 |

首次启用钩子：`./scripts/install-hooks.sh`（换机器或重新 clone 后需重跑）。
状态留痕机制的细节见 `docs/state/README.md`。

### 12.7 提交粒度与可回退

- **一个独立功能一次提交**；DDL 变更**单独一次提交**（`db:` 前缀），便于单独回滚。
- 改核心逻辑前后各自有可回退点：改之前先 commit 一次（哪怕只是加测试）。
- 迁移前必须走 `./scripts/migrate-safe.sh`（自动 `pg_dump` 到 `backups/`，失败时打印 `pg_restore` 命令）。
- 里程碑收尾打 tag：`git tag -a v0.1-m4 -m "M4 消耗域完成"`，需要回退时 `git checkout v0.1-m4`。
- 提交信息里若涉及行为变更，写清"改了什么行为 + 影响哪条验收用例"。

