# 变更记录

格式参考 Keep a Changelog：`新增 / 变更 / 修复 / 移除 / 数据库 / 文档`。
每次提交若涉及数据库变化，必须在「数据库」小节写明表、字段、索引的增删改，以及是否需要重建或迁移。

---

## 2026-11-09 · 阶段 1：项目初始化

### 新增

- **三容器架构**：`db`（PostgreSQL 16）/ `api`（FastAPI，容器内 8000，不对外）/ `web`（nginx 托管 dist 并反代 `/api`，对外 8080）。
- `frontend/Dockerfile`（node 构建 → nginx）、`frontend/nginx.conf`（gzip、静态长缓存、SPA 回退、`/api` 反代、`/health` 透传）。
- 后端：`core/logging.py`（JSON/纯文本双格式、按 request_id 串联、滚动文件）、`api/v1/system.py`
  （`/health`、`/ping`、`/system/db`、`/system/client-logs`）、`api/v1/router.py`、连接池参数化。
- 前端：`api/http.ts`（Axios 实例 + 请求 id + 统一错误 + 401 出口）、`api/index.ts`、
  `utils/logger.ts`（全局异常捕获 + 批量上报）、`utils/notify.ts`（Naive UI 离散提示）、
  `layouts/AppLayout.vue`（顶部栏 + 桌面侧边栏 + 移动底部导航）、`stores/app.ts`。
- 目录：`storage/{uploads,exports,logs}`、`backups/`（只留 `.gitkeep`，内容不入库）。

### 变更

- `backend/alembic/` → **`backend/migrations/`**（按约定命名），`alembic.ini` 的 `script_location` 同步。
- API 端口从 8080 改为 **8000**（仅容器内）；对外统一走 web 容器的 8080。
- `/api/v1/*` 响应统一为 `{success, data, message, request_id}` 信封（此前 `/ping`、`/health` 返回裸对象，
  导致前端取 `data` 为空并误报"无法连接后端"）。
- 连接池状态字段由 `overflow`（会变负、语义歧义）改为 `max_overflow`（配置上限）。
- `.env.example` 补齐日志、连接池、端口等变量。

### 修复

- 前端 `vue-tsc` 两处类型错误：路由数组缺 `RouteRecordRaw[]` 标注；Vite 8 的 `manualChunks` 只接受函数形式。
- 容器内 `npm ci` 因 macOS 生成的 lockfile 缺少 linux-musl 可选依赖而失败 → 改用 `npm install`；
  同时容器内直连 registry.npmjs.org 出现 ECONNRESET → 默认改用 npmmirror（可用 `NPM_REGISTRY` 覆盖）。

### 数据库

- 无结构变更（仍为 25 表 / 2 视图 / `0001_init`）。验证：干净库 `alembic upgrade head` → 25 表 + `0001_init`。

---

## 2026-11-09 · 阶段 2：基础资料管理

### 新增

- **认证（2.1）**：`/auth/{pair,login,logout,me,devices,password,password/set,policy}`。
  Web 下发 HttpOnly Cookie（`fk_sid`），App 返回 Bearer 令牌；密码用 argon2id 哈希；
  配对码一次性、10 分钟过期、只存 SHA-256；设备可吊销且即时生效。
- **基础字典（2.2/2.3/2.4）**：分类（两级 + 排序 + 引用保护）、单位（9 个内置，维度隔离）、
  储存位置、营养项目字典（6 项）。`python -m app.cli seed` 幂等写入，容器启动时自动执行。
- **食材档案（2.5）**：新增/编辑/详情/停用启用；`name_pinyin` / `name_initials` 写入时生成；
  详情返回分类路径（「肉类 · 常见食材」）、六项属性展示值与 `can_convert` 标记。
- **图片（2.6）**：`/files/upload`（魔数校验 jpg/png/webp、≤5MB、sha256 去重）、`/files/{id}/raw`、删除。
- **搜索（2.7）**：中文模糊 / 全拼 / 首字母三路 OR + 相关性排序；`/ingredients/search` 提供联想。
- **条码（2.8）**：`/barcodes` 绑定/解绑，`GET /barcodes/{code}` 反查食材。
- **换算校验**：`GET /ingredients/{id}/conversion`，无 `default_unit_weight` 时返回
  `422 UNIT_NOT_CONVERTIBLE`，不做任何推算。
- 前端：`LoginView`（配对码/密码双 Tab）、`InventoryView`（搜索 + 分类/位置筛选 + 停用可见性）、
  `IngredientDetailView`（分类标签 + 启用状态 + 六项属性表 + 图片/营养/条码）、
  `IngredientFormView`（含换算联动提示）、`SettingsView`（设备/密码/分类/单位/位置）。
- 测试：`tests/conftest.py`（真实 PG 测试库 + 清库夹具）、`tests/api/test_stage2.py`（25 项）、
  `tests/api/test_system.py`（6 项）、`tests/unit/test_pinyin.py`（11 项）。

### 变更

- 迁移目录 `backend/alembic/` → **`backend/migrations/`**（对齐约定命名）。
- 存储路径默认值：`DATA_DIR` / `STORAGE_DIR` / `BACKUP_DIR` 未设置时回落到仓库内 `storage/`、`backups/`，
  不再硬编码 `/data`（该硬编码曾导致本机测试时上传接口 500）。
- 食材列表默认只返回启用项，管理端用 `include_inactive=true` 查看全部。
- 分类 `/sort` 路由注册到 `/{category_id}` 之前（否则 "sort" 会被当作 UUID 解析而 400）。
- 分页/数值：金额与重量仍以**字符串**传输；`Dec2/Dec3/Dec4` 的序列化改为 `when_used="json"`，
  python 模式保留 `Decimal`（此前 `model_dump()` 返回字符串，导致 `unit_weight <= 0` 抛 TypeError）。

### 修复

- `IngredientIn/Update` 中可空数值字段漏写 `| None`，导致传 `null` 清空换算关系被 Pydantic 拒绝。
- 容器内测试时 `LOG_DIR` / `STORAGE_DIR` 指向 `/data` 不存在 → 启动告警并 500。

### 数据库

- **新增迁移 `0002_ingredient_storage`**：`ingredients` 增加 `default_storage_location_id`
  （FK → `storage_locations`，`ON DELETE SET NULL`）与部分索引 `ix_ingredients_location`。
- `database/001_init.sql` 同步该列（新建库直接含此列，`0002` 为空操作）。
- 迁移版本：`0001_init` → **`0002_ingredient_storage (head)`**。
- 表数仍为 25（未新增表，只补列）。

---

## 2026-11-09 · M0 收尾：网段白名单 + 写操作幂等

### 新增

- `app/core/middleware.py`：两个**原生 ASGI** 中间件（不用 BaseHTTPMiddleware，避免读 body 与 call_next 冲突）。
  - `CidrMiddleware`：按 `ALLOW_CIDR` 校验来源网段，非白名单返回 403 统一信封；
    回环与非 IP 客户端（测试客户端、本地 socket）放行，保证 `pytest` 与健康检查不被误拦。
  - `IdempotencyMiddleware`：写方法带 `Idempotency-Key` 时，同 key 同 body 返回原响应
    （附 `Idempotency-Replayed: 1`），同 key 不同 body 返回 409 `DUPLICATE_REQUEST`；
    只缓存 2xx JSON 响应，失败响应不缓存；顺带清理 24 小时前的旧记录。
- `models.IdempotencyKey` ORM 映射；`main.py` 按 `CIDR → 幂等 → 请求上下文 → CORS → 路由` 顺序挂载。
- `tests/api/test_middleware.py`：14 项（CIDR 判定矩阵 7 组 + 真实 ASGI 403 + 幂等四态）。

### 变更

- `/api/v1/*` 的 CORS `expose_headers` 增加 `Idempotency-Replayed`。
- `docs/PROJECT_STATUS.md` 重写：里程碑表、未完成清单、已知问题（K11~K14）、三处状态交叉核对命令。

### 修复

- 本机 PostgreSQL 库迁移版本停在 `0001_init`（容器库已是 `0002`），在本机直连后端会缺
  `ingredients.default_storage_location_id` 列。已用 `scripts/migrate-safe.sh` 迁移（先备份到
  `backups/pre-migrate-freshkeep-20261109-015103.dump`），两库现均为 `0002_ingredient_storage`。

### 数据库

- 无 DDL 变更。`idempotency_keys` 表在 `0001_init` 中已建，本轮只新增 ORM 映射与写入逻辑。
- 迁移版本：`0002_ingredient_storage`（本机库与容器库一致）。

### 验证

- pytest **56 passed**（原 42 + 中间件 14）。
- 反向验证：把幂等命中分支临时改成 `if False:`，`test_idempotent_replay_returns_original_response`
  立即变红，确认该测试真的在测东西；随后恢复原文件并复跑全绿。
- 容器上 curl 实测：同 key 同 body 两次都返回 201 且 `id` 相同（第二次 `replayed=1`）；
  同 key 不同 body 返回 409 `DUPLICATE_REQUEST`；库中 `idempotency_keys` 仅 1 条、`categories` 仅 1 条。
- CIDR 判定（容器内）：`172.18.0.1`/`192.168.31.50`/`100.64.1.1`/`127.0.0.1` 放行，`8.8.8.8` 拒绝。

---

## 2026-11-09 · M3：批次域（入库 / 查询 / 状态机）

### 新增

- **入库五步事务**（AGENTS.md §4.2）：`POST /batches` 在同一事务内写
  `batches` + `inventory_transactions(type=purchase)` + `transaction_allocations`（自分配），
  并断言 `Σ allocation == transaction.delta == batch.remaining_*`，不等即回滚。
- 批次接口：`GET /batches`（分页 + 食材/位置/状态筛选）、`GET /batches/{id}`、
  `GET /batches/expiring?days=7`、`GET /batches/expired`、`PUT /batches/{id}`（仅元数据）。
- `services/inventory/state.py` 状态机：`active → depleted`（剩余归零）、
  `depleted → active`（恢复库存），`void` 未开放（需反向流水，留 M4/M5）。
- ORM：`Batch`、`InventoryTransaction`、`TransactionAllocation`；`schemas/batch.py`；
  `core/time.py`（`biz_today()` / `days_until()`，统一 Asia/Shanghai 业务日期）。
- 编号规则：批次 `yyyymmdd-NN`、流水 `TX-P-yyyymmdd-NN`（当日序号 + 唯一约束兜底）。
- 重量单位换算：`g`→1、`kg`→×1000，统一按克入库；数量/重量单位维度校验（重量位填「包」→ 400）。
- 前端：`api/batches.ts`；食材详情页新增批次区（剩余量/成本/临期标签）与「＋ 入库」表单，
  双计量、数量与重量至少填一项，空态给出下一步动作。
- 测试：`tests/api/test_batches.py`（18 项：五步事务、对账视图、双计量、kg 换算、
  编号递增、临期/过期、禁改字段、鉴权）、`tests/unit/test_batch_state.py`（9 项状态迁移）。

### 变更

- `AGENTS.md §12.5` 的核心逻辑保护表：库存流水与批次分配已有 Python 断言（见下「遗留」）。
- `GET /batches` 分页响应与阶段 2 的 `GET /ingredients` 对齐为 `data={items:[...], total, page, page_size}`。

### 修复

- **列表响应结构多套一层**：初版返回 `data.items.items`，前端 `PageResult` 拿到的 `items`
  是对象而非数组 → 批次区只显示按钮、数据不渲染。由浏览器 DOM 探针发现（不是看截图猜），
  修后端结构并同步测试断言，重建容器后 1280/390 两种宽度 DOM 探针全部 true。
- `expiring` 查询初版只有上界没有下界，已过期批次会混进临期列表 → 补 `expiry_date >= today`。

### 数据库

- **无 DDL 变更**，无新迁移；迁移版本仍为 `0002_ingredient_storage (head)`。
- 本轮只新增对既有表的 ORM 映射与写入逻辑；`v_batch_reconcile` 在容器真实入库后差异为 0。

### 验证

- pytest **83 passed**（原 56 + 批次接口 18 + 状态机 9）。
- 容器真实 HTTP **18 项全过**：`POST /batches` 201、`batch_no=20261109-01`、
  分配记录 1 条、对账 diff `0.000/0.000/0.00`、`unit_cost=0.0360`、
  PUT 改元数据 200 / 改数量 400、幂等同 key 同 body 返回同一 id 且只落 1 条流水+1 条分配。
- 浏览器 DOM 探针：详情页 1280 / 390 均显示批次区、批次号、剩余 500g、临期标签、¥18.00、
  入库弹层字段齐全；横向溢出 0px、卡片越界 0 个。

### 遗留

- `services/inventory/` 的 Python 断言目前在 `tests/api/`，尚未平移到
  `tests/acceptance/`（AGENTS.md §12.5 要求）；M4 消耗域时一并建立 acceptance 层。
- 批次编号用「当日计数 + 唯一约束兜底」，并发同日入库存在极小概率冲突，未加重试；
  单用户低频场景可接受，M4 若引入批量入库需改数据库序列。

---

## 2026-11-09 · M4：消耗域（FEFO / 成本 / 营养快照 / 撤销）

### 新增

- **验收层 `backend/tests/acceptance/test_consumption.py`**：PRD §7.1 的 9 条用例从
  `database/002_acceptance_check.sql` 平移成真实 HTTP + 真实 PG 事务的 pytest，
  开工前先确认 9 条全红（AGENTS.md §12.5）。
- `services/consumption/`：`consume()` 五步事务（流水 → 批次缓存 → 分配 → 一致性断言 → 单据/快照）、
  FEFO（`ORDER BY expiry_date NULLS LAST, purchase_date, id` + `FOR UPDATE OF batches`）、
  尾差结清、双计量解析、营养快照冻结；`reverse()` 反向流水恢复库存；`state.py` 状态机。
- `api/v1/consumptions.py`：`POST /consumptions`、`/batch`、`GET /consumptions`、`/{id}`、
  `POST /{id}/reverse`；`/batch` 注册在 `/{id}` 之前。
- `PUT /ingredients/{id}/nutrition`：**补齐 docs/api.md §3.2 已声明但阶段 2 未实现的缺口**——
  整体替换当前版本营养档案（旧行 `is_current=false`、新行 `version+1`），历史快照不受影响。
- ORM：`ConsumptionRecord`、`ConsumptionNutrition`；`schemas/consumption.py`。
- 前端：`api/consumptions.ts`、`ConsumeView.vue`（预选食材/双计量输入/结果区含成本与营养）、
  `RecordsView.vue` 从 14 行占位换成真实消耗列表（状态筛选/撤销/空态）；
  库存页与详情页加入口，路由新增 `/consume`。

### 变更

- `main.css` 增加 `.head-actions`；`NutritionReplace` 从路由模块移到 `schemas/ingredient.py`
  （与现有分层一致，同时修掉 OpenAPI 生成时的 forward-ref 失败）。
- 记录页目前只展示消耗记录；入库/盘点/报损流水依赖 M5 的 `/inventory/transactions`，页面已标注。

### 修复

- **行锁与 eager-load 冲突**：`Batch.ingredient` / `storage_location` 是 `lazy="joined"`（OUTER JOIN），
  PostgreSQL 拒绝 `FOR UPDATE` 作用于外连接可空侧 → 改为 `with_for_update(of=Batch)` 只锁主表。
- 反向验证：临时去掉 `with_for_update`，并发用例立即变红（500），恢复后通过，证明行锁是并发正确性的关键。

### 数据库

- **无 DDL 变更**，无新迁移；迁移版本仍为 `0002_ingredient_storage (head)`。
- 本轮只新增对既有表的 ORM 映射与写入逻辑；容器真实消耗/撤销后 `v_batch_reconcile` 差异始终为 0。

### 验证

- pytest **92 passed**（原 83 + 验收层 9）；全量含阶段 2、M0、M3 回归用例。
- 容器真实 HTTP **22 项全过**：成本 10.80、剩余 42.20、营养 495.0000、对账 diff 全 0、
  库存不足 422、批量整批回滚、撤销恢复 1500g 且原记录 `reversed`、幂等只产生一笔、
  `GET /consumptions/{id}` 含分配与快照。
- 浏览器：消耗页/记录页 1280/390 DOM 探针横向溢出 0px；真实点击提交消耗后结果区显示 ¥3.60 与批次分配。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 双计量按批次**实际比例**同步另一维度（不是按食材换算关系推算），单用户场景可接受。
- 营养基准单位只接受 g/kg；体积或「份」基准返回 `NUTRITION_BASIS_MISMATCH`（PRD §8 不做密度换算）。
- 记录页的完整流水视图待 M5；消耗列表目前固定取最近 50 条，未做翻页 UI。

---

## 2026-11-10 · M5：库存域（聚合 / 流水 / 盘点 / 报损）

### 新增

- `GET /inventory`：读 `v_inventory`，支持中文/拼音/首字母搜索、分类（含子分类）、
  储存位置（EXISTS 子查询）、低库存筛选与分页；返回最近到期与剩余天数。
- `GET /inventory/summary`：总重量、总成本、总数量、食材数、批次数、低库存数、临期 7 天、已过期。
- `GET /inventory/transactions`：全部流水（purchase/consume/spoilage/adjustment/reverse），
  类型/食材/日期过滤 + 分页；行内含 `related_object_id`，前端据此撤销消耗。
- `POST /inventory/adjustments`：盘点提交**实际值**、服务端反算 delta；
  盘亏按单位成本扣减、扣到归零时取剩余成本结清尾差；盘盈按当前单位成本计入。
- `POST /inventory/stocktake`：批量盘点，任一项失败整批回滚。
- `POST /inventory/spoilage`：报损按 FEFO 扣批次，写 `spoilage` 流水；原因必填。
- `services/inventory/ops.py`：盘点/报损的五步事务实现（复用 `fefo_order`、
  状态机与一致性断言，不复制消耗域的业务规则）。
- 测试：`tests/acceptance/test_inventory.py` 14 项（聚合/汇总/搜索/流水/盘亏/盘盈/
  归零结清/批量回滚/报损 FEFO/鉴权）。
- 前端：记录页改为完整流水（类型标签 + 筛选 + 消耗撤销）；库存页加汇总条；
  食材详情页批次行加「盘点」、批次区加「报损」弹层；`api/inventory.ts`。

### 变更

- 记录页从「只显示消耗」升级为「全部流水」，撤销入口按 `related_object_type=consumption` 判定。

### 修复

- **盘盈违反 DDL 约束**：`ck_batch_remaining_le_initial` 要求 `remaining <= initial`，
  盘盈会让剩余量超过初始量 → 盘盈时同步上调 `initial_weight/initial_quantity/purchase_cost`
  （语义：当初入库少记了，只升不降）。
- **`text()` 参数绑定**：`:param::uuid` 不被 SQLAlchemy 识别（bindparam 正则 `(?!:)`），
  改为 `CAST(:param AS uuid)`；`:q IS NULL` 让 PG 无法推断类型，改为 `COALESCE(CAST(...), 列)`。
- **测试日期漂移**：`test_expiring_and_expired_batches` 硬编码 `2026-11-11` 并断言「剩 2 天」，
  11-10 运行时按实际只剩 1 天而失败 → 测试日期一律改为基于 `biz_today()` 相对计算
  （`test_batches.py`、`test_consumption.py` 一并修正）。
- **测试夹具**：库存测试的食材改用 API 建档，否则 `name_pinyin` 为空会让拼音搜索用例假失败。

### 数据库

- **无 DDL 变更**，无新迁移；迁移版本仍为 `0002_ingredient_storage (head)`。
- 盘点盘盈会更新 `batches.initial_*` 与 `purchase_cost`（只升不降），这是业务语义要求，
  不改变表结构。

### 验证

- pytest **106 passed**（原 92 + 库存域 14）。
- 容器真实 HTTP **16 项全过**：聚合 1500g/53.00、汇总、盘亏 -20g/-0.72、盘盈 +20g 且
  initial 上调、批量盘点整批回滚、报损 600g 后剩余 b1=0/b2=900、流水类型过滤、
  `v_batch_reconcile` 差异为 0。
- 浏览器 DOM 探针：记录页（流水类型/单号/筛选）、库存页（汇总条）、详情页（盘点/报损按钮）
  在 1280/390 下全部可见且横向溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 每日对账任务（APScheduler）尚未实现，留到 M7 与备份任务一起做；当前靠
  `v_batch_reconcile` 在每次写入后断言。
- 盘点只支持按重量主维度核算成本；同时改数量时按重量计成本，数量差异不单独计价。
- 记录页固定取最近 60 条，未做翻页 UI（接口已支持）。

---

## 2026-11-10 · 阶段 3：采购入库与批次管理

### 新增

- **独立入库页面** `views/PurchaseView.vue`（路由 `/purchase`）：食材可搜索选择，
  数量/重量/价格/单位成本预览 + 购买/生产/到期/开封四个日期 + 储存位置 + 备注；
  提交后展示批次号、初始/剩余重量、单位成本与 `TX-P-` 流水号，可跳批次详情或继续入库。
- **批次列表页** `views/BatchesView.vue`（`/batches`）：跨食材列出全部批次，
  支持中文/拼音搜索、状态（有库存/已耗尽/全部）与储存位置筛选，行点击进详情。
- **批次详情页** `views/BatchDetailView.vue`（`/batches/:id`）：初始/剩余重量与数量、
  采购/剩余/单位成本、四个日期、位置、备注，以及**该批次的流水**（按分配表反查）。
- 后端：`BatchCreate` 增 `opened_date`（入库即可填开封日期）；
  `GET /batches` 增 `q` 参数（食材中文/拼音/首字母）；
  `GET /inventory/transactions` 增 `batch_id` 参数（经 `transaction_allocations` 反查，
  一条跨批次流水会同时出现在各批次下）。
- 测试：`tests/acceptance/test_purchase.py`（7 项），覆盖 6 条验收标准 +
  四日期、批次列表搜索、批次详情与按批次查流水。

### 变更

- 食材详情页的「＋ 入库」改为跳转独立入库页（`/purchase?ingredient=`），
  批次行新增「详情」入口；库存页新增「批次」与「+ 采购入库」按钮。
- `docs/api.md` 的入库样例补 `production_date` / `opened_date`，流水与批次列表补过滤参数。

### 数据库

- **无 DDL 变更**，无新迁移；`opened_date` 列在 `0001_init.sql` 建表时已存在，
  本轮只是把入库接口的写入通道打开。

### 验证

- pytest **113 passed**（原 106 + 阶段 3 的 7 项）；先确认 7 项中 2 项红（`opened_date`、
  `q` 搜索），实现后全绿。
- 容器真实 HTTP **17 项全过**：两批次独立（`20261110-01/02`）、四日期、
  位置「冷冻室」、单位成本 0.0360/0.0400、purchase 流水 2 条共 1500g、
  `q` 搜索 total=2、按 `batch_id` 只返回该批次 1 条流水、
  幂等同 key 同一批次、库存 1800.000 == 流水 1800.000、对账差异 0。
- 浏览器：入库页 4 个日期输入齐全，真实填表提交 500g/18 元后结果区显示批次号、
  `TX-P-` 流水号与 `0.0360`；批次列表与详情 1280/390 全部字段可见、横向溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 批次详情页的盘点/报损仍从食材详情页发起，未在批次详情内直接提供入口。
- 批次列表未做分页 UI（固定取 60 条，接口已支持分页）。

---

## 2026-11-10 · 阶段 4：库存引擎（测试先行）

### 新增

- **独立库存引擎** `services/inventory/engine.py`：纯函数层，无 IO/无事务，
  负责 FEFO 排序、扣减计划、成本分摊、尾差结清、双计量比例、流水重算、对账差异判定。
  `FefoBatch` / `DeductionPlan` / `DeductionItem` 三个不可变数据结构。
- **4.1 流水口径库存** `GET /inventory/ledger-stock`：按 `Σ有效流水` 重算并逐食材对照批次缓存，
  返回 `consistency = ok / mismatch` 与不一致计数。
- **4.12 对账与修复**：`GET /inventory/reconcile` 列出 `v_batch_reconcile` 中 diff 非 0 的批次；
  `POST /inventory/reconcile/repair` 按分配聚合覆盖缓存，并写
  `audit_logs(action='reconcile_repair')`（AGENTS.md §4.2 允许的唯一例外场景）。
- 测试：`tests/unit/test_inventory_engine.py`（17 项纯函数）、
  `tests/acceptance/test_stage4_engine.py`（10 项，含 8 项必须测试）。
- 报告：`docs/reports/cost-accounting.md`（成本核算测试报告，含实跑输出）。

### 变更

- `docs/api.md` 补三个新端点到「库存」清单。

### 数据库

- **无 DDL 变更**，无新迁移；`audit_logs` 表在 `0001_init.sql` 已存在，本轮开始真正写入。

### 验证

- pytest **140 passed**（原 113 + 引擎 17 + 阶段 4 验收 10）。
- 8 项必须测试全绿：分配批次、库存不足整笔失败、批量回滚、并发不超卖、
  撤销反向流水、归零成本归零、重复提交不重复扣、手动调整生成流水；
  另加 4.1 流水口径与 4.12 对账修复。
- 成本数字与 PRD 一致：消耗 300g → 10.80；剩余 200g/7.20 + 1000g/35.00；
  总成本 42.20；尾差场景 10.00（非 9.99）；多批次 18.00 + 3.50 = 21.50；对账差异 0。
- 容器真实 HTTP 复核同一组数字（见报告 §4）。

### 遗留

- `reconcile/repair` 需要人工或定时任务触发，尚未接入 APScheduler（K21）。
- 引擎暂未被 `consumption` / `ops` 复用（两处仍各自实现分配循环），
  避免在无测试覆盖的情况下重构已通过的消耗路径；后续可在等价性测试保护下统一。
- 数量维度的库存对照未纳入 `ledger-stock`（当前只对照重量与成本）。

---

## 2026-11-11 · M6：首页与营养统计

### 新增

- `GET /dashboard/summary`：库存总价值/总重量/食材数/批次数、期间采购/消耗/报损金额、
  消耗比例、最近 4 条入库、临期 7 天/已过期/低库存计数；支持 `from_date/to_date`（默认近 30 天）。
- `GET /dashboard/nutrition?period=today|3d|week`：六项营养素按**消耗快照**汇总，
  返回窗口起止、`days`、`has_records`、`record_count`、单项目标与达成率、免责说明。
- `GET/PUT /nutrition/targets`：营养目标读写；同日重复设置用 `ON CONFLICT` 覆盖，
  历史日期保留；读取取每个 (code, period) 最新生效行。
- `services/dashboard.py`：窗口计算（Asia/Shanghai 自然日）、金额统计、营养聚合、目标 upsert。
- `views/DashboardView.vue` 重写：库存价值大卡 + 期间金额 + 提醒条 + 最近入库 + 营养卡片
  （周期切换、目标达成率、空态文案「这段时间没有消耗记录」）；`api/dashboard.ts`。
- 测试：`tests/acceptance/test_dashboard.py`（11 项）。

### 变更

- 首页从「链路自检卡片」改为业务数字，左右顶栏保留一行状态角标。
- `docs/api.md` 补 4 个新端点到清单。

### 数据库

- **无 DDL 变更**，无新迁移；`nutrition_targets` 在 `0001_init.sql` 已存在，本轮开始读写。

### 验证

- pytest **151 passed**（原 140 + 首页 11）。
- 容器真实 HTTP **21 项全过**：空状态 `has_records=false` 且比例为 `null`；消耗 300g →
  热量 `495.0000`；采购 53.00 / 消耗 10.80 / 比例 0.2038；`today/3d/week` 天数 0/2/6；
  目标同日覆盖为 2100、达成率 0.2357、库中仅 1 行；撤销后记录数 2 → 1。
- 首页 1280/390 DOM 探针：空状态显示「这段时间没有消耗记录」且不称「摄入 0」；
  有数据时库存价值、批次号、495、免责声明、目标均可见；横向溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 营养目标只做 `daily` 视图的达成率；`weekly` 目标已存但未参与展示换算。
- 首页「期间」默认近 30 天，暂未做前端日期选择器（接口已支持）。

---

## 2026-11-11 · 阶段 5：库存管理界面

### 新增

- `GET /inventory` 增 `status` 参数：`normal`（有货且非临期）/ `expiring`（7 天内到期且有货）/
  `expired`（已过期且有货）/ `out_of_stock`（零库存）；与 `q`、`category_id`、`location_id`
  可任意组合，返回交集。
- **库存总览改版**（`InventoryView`）：数据源从食材档案接口换成 `/inventory` 库存聚合，
  列表显示剩余量/成本/批次数，带状态标签（正常/临期/已过期/无库存）、低库存标记、
  行内「− 消耗」按钮与多选批量模式。
- **快速消耗**：列表行直接弹出消耗表单（重量/数量），提交后刷新列表与汇总。
- **批量消耗**：多选 → 批量弹层逐项填量 → `POST /consumptions/batch`（整批回滚），
  底部悬浮操作栏支持全选。
- **盘点 / 报损页**（`StocktakeView`，`/stocktake`）：盘点按批次录入实际重量（只提交有差异的行，
  走 `/inventory/stocktake`）；报损按食材 FEFO 扣批次（走 `/inventory/spoilage`）；
  下方展示最近 adjustment/spoilage 记录用于追溯。
- **食材详情**补「历史记录」（最近 20 条流水）与批次行的「单位成本」。
- **记录页**加日期区间筛选与分页（上一页/下一页 + 页码）。
- 测试：`tests/acceptance/test_stage5_filters.py`（7 项：四状态 + 四条件组合 + 聚合字段）。

### 变更

- 库存页移除「含停用」勾选：`v_inventory` 只含启用食材（停用食材在档案页管理）。
- `docs/api.md` 的库存清单补 `status` 参数。

### 数据库

- **无 DDL 变更**，无新迁移；迁移版本仍为 `0002_ingredient_storage`。

### 验证

- pytest **158 passed**（原 151 + 阶段 5 筛选 7 项）。
- 浏览器实测：状态「临期 7 天」筛出 1 个食材（其余两个被排除）；移动端 390 点「− 消耗」→
  填 100 → 提交，DB 从 500 变 400；批量消耗勾选两项填 50/60 → 批次变为 440/450 且生成 2 张消耗单；
  盘点页 tab/批次行/最近记录齐全；详情页「单位」「成本」「历史记录」可见；
  记录页两个日期输入 + 上一页/下一页；所有页面横向溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 盘点页只支持按食材逐个盘点，没有「扫码快速盘点」；批量盘点接口已支持，前端未做跨食材一次提交。
- 库存列表一页取 100 条，未做分页 UI（家庭规模食材百级内够用）。

---

## 2026-11-11 · 阶段 6：首页与统计

### 新增

- `GET /stats/overview?granularity=day|week|month|year&from_date=&to_date=`：
  一次返回库存价值（剩余成本）、采购/消耗总额与时间序列、分类占比、消耗排行、库存周转、最近 8 条操作。
- `services/stats.py`：粒度分桶（day/week/month/year，含无数据桶补齐）、
  Asia/Shanghai 自然日窗口、流水聚合、分类/排行/周转查询。
- `components/StatsPanel.vue`：概览 4 卡 + 内联 SVG 双折线趋势 + 分类占比条 + 消耗排行条 +
  周转表 + 最近操作；粒度切换与自定义日期区间。
- 首页接入统计面板，移除与之重复的「期间金额」卡片。
- 测试：`tests/acceptance/test_stats.py`（15 项）。

### 变更

- 首页布局：提醒条 → 统计面板 → 最近入库 → 营养，统计面板承载 6.1~6.9。

### 数据库

- **无 DDL 变更**，无新迁移；统计全部基于既有流水表与视图。

### 验证

- pytest **173 passed**（原 158 + 统计 15）。
- 容器接口实测：采购 106.00、消耗 28.80、库存价值 77.20，三者与流水/剩余成本逐项一致，
  且库存价值 ≠ 采购总额；day/week/month/year 分别 30/13/13/6 个桶，序列之和等于总额；
  自定义单日窗口只含当天，未来区间金额 0 且 `has_data=false`。
- 浏览器：首页 1280/390 均显示 4 张概览卡、趋势折线、分类占比、排行、周转、最近操作与粒度按钮；
  切「按月」后 X 轴显示 `2025-11 ~ 2026-11`；横向溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 分类占比只按一级分类聚合，未细分到二级分类。
- 周转率目前是「采购次数/消耗次数/消耗量」，未计算「平均库存天数」这类派生指标。

---

## 2026-11-11 · 阶段 7：营养管理

### 新增

- `GET /dashboard/nutrition` 增 `month` 周期（自然月至今），返回 `period_target`（日目标 × 天数）。
- `PUT /ingredients/{id}/nutrition` 支持 `source`（manual / packaging_label / database），
  非法值返回 400；详情响应补 `source` / `version` / `basis_unit_id`，便于前端编辑后整体回传。
- 详情页营养档案：显示来源标签与版本，新增编辑弹层（逐项改值 + 选来源），
  保存后提示「历史消耗快照不受影响」。
- 首页营养卡新增「本月」，多日窗口展示「窗口目标」（日目标 × 天数）；空态也展示推算说明。
- 测试：`tests/acceptance/test_nutrition_stage7.py`（11 项）。

### 变更

- 达标率口径修正：原先一律用日目标做分母，3d/week/month 会算高；
  现按 `日目标 × 窗口天数` 计算，`target_value` 仍返回日目标。

### 数据库

- **无 DDL 变更**；`ingredient_nutrition.source` 与 `consumption_nutrition.basis_snapshot`
  在 `0001_init.sql` 已存在，本轮把 source 的写入通道打开。

### 验证

- pytest **184 passed**（原 173 + 营养 11）。
- 容器实测：200g 鸡胸肉 → 330.0000 / 62.0000 / 7.2000；改档案蛋白 30g 后历史快照仍 62、
  今日统计仍 62、新消耗 60（累计 122）；month 窗口 2026-11-01~2026-11-11，
  达成率按 22000 目标换算（0.0300）；3d 达成率按 6000 换算（0.1100）；
  非法 source 返回 400。
- 浏览器：详情页显示来源标签与「营养快照」说明，编辑弹层 3 行可保存（热量改 160 已落库，
  历史快照仍 330）；首页营养卡四个周期按钮，「本月」点击后高亮正确；空态显示推算说明。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留

- 达标率只对 `daily` 目标做换算，`weekly` 目标已存但未参与展示。
- 营养档案编辑为「整体替换」，一次只能提交当前显示的项，未做单项删除。

---

## 2026-11-11 · 文档更正：M8 与翻页 UI 的滞后描述

### 文档

- `PROJECT_STATUS.md`
  - 里程碑表：**M8 由「🔄 部分」更正为「✅ 完成」**，列出 13 个实际视图，
    并说明 401 由 `AppLayout` 全局 handler 跳登录（原文写「记录页完整流水待 M5」，M5 早已交付）。
  - 未完成清单：**删除「消耗列表翻页 UI 未做」**——阶段 5 已给记录页加
    `page_size=30` + 上一页/下一页 + 日期区间筛选。
  - 未完成清单：新增真实遗留 **`PairView.vue` 无引用（14 行死文件，可安全删除）**。
  - 进度表述：从模糊的「P0 完成 9/13 个里程碑（约 69%）」改为可核对的完成清单
    （阶段 0~7 与 M0~M6、M8 已完成；剩余 M7 / M9 / M10）。
- `DEVELOPMENT_PLAN.md`：M8 段由计划态改为完成态，补 10 个页面的交付表与完成判据。

### 说明

本轮只改文档，未改动任何代码与数据库；184 项测试、迁移版本、容器状态均未受影响。

---

## 2026-11-11 · 阶段 8（上）：AI 识别闸门 / 条码 / 临时提醒 / 采购建议

### 新增

- **识别草稿表** `recognition_drafts`（迁移 `0003`）：AI 结果只落此表，
  含 `draft`（规范化字段）、`warnings`（校验提示）、`status`、`confirmed_entity_*`。
  与 `batches` / `inventory_transactions` 零耦合。
- **AI 服务层** `services/ai/`：`config`（app_settings 读写、密钥脱敏）、
  `provider`（stub / openai_compatible，超时与异常降级）、`validate`（日期校验纯函数）。
- **识别接口**：`POST /ai/recognitions`、`GET/PATCH /ai/recognitions/{id}`、
  `POST .../confirm`（ingredient 建档 / batch 入库）、`POST .../reject`、`GET/PUT /ai/settings`。
  确认写 `audit_logs(action='recognition_confirm')`。
- **条码与商品源**：`GET /products/lookup`（本地优先，其次外部源）、`GET/PUT /products/source`；
  外部源 kinds：none / openfoodfacts / custom；**拒绝内网地址（SSRF）**。
- **提醒** `services/alerts.py`：`POST /alerts/scan`（三条 `INSERT ... WHERE NOT EXISTS`，幂等）、
  `GET /alerts/summary`、`GET /alerts/notifications`、单条/全部已读。
- **采购建议** `GET /purchase/suggestions`：最低库存差额优先，未设最低时按近 30 天用量估算 7 天覆盖。
- **前端**：`ScanView`（摄像头扫码 / 手动条码 / 拍照识别 / 待确认表单含警告与修正 / 确认建档或入库）、
  `AlertsView`（统计卡 + 通知中心 + 采购建议）；库存页与首页加入口；`api/ai.ts`、`api/alerts.ts`、`api/files.ts`。

### 变更

- `database/001_init.sql` 同步新增 `recognition_drafts`；业务表数 25 → 26（`test_system` 断言同步）。
- 所有直接返回 dict 的接口把 Decimal 转字符串（`purchase/suggestions` 曾因序列化成 float 丢精度）。

### 数据库

- 迁移 `0003_recognition_drafts`，本机库与容器库均已升级；`alembic heads` = `0003_recognition_drafts`。

### 验证

- pytest **200 passed**（原 184 + 阶段 8 的 16）。
- 容器真实 HTTP **26 项全过**：识别/修正阶段批次与流水零变化、`DATE_SWAPPED` 自动交换、
  确认建档（拼音可搜、审计已写）、确认入库（批次 +1 / 流水 +1 / 对账 0）、
  条码本地命中、内网源被拒、扫描幂等（第二次 created=0）、已读计数、建议量为字符串。
- 浏览器 390：手动链路 查询→手动填写→待确认（`NAME_MISSING`）→确认建档→跳详情，DB 落库；
  提醒页扫描后出现低库存通知与采购建议；两页 1280/390 溢出 0px。
- `npm run build` 通过（vue-tsc 零错误）。

### 遗留（阶段 8 下半）

- 8.11 菜谱管理、8.12 菜谱匹配、8.13 采购清单未做（表已在 `0001`）。
- 8.8 的 PWA 通知未接（Web Notification + Service Worker）；目前是应用内通知中心。
- 8.7 定时扫描未接 APScheduler（当前手动触发）；与 M7 一起做。
- 视觉模型未配置时降级为空白草稿 + `AI_NOT_CONFIGURED` 提示（设计如此，非缺陷）。

---

## [Unreleased]

### 新增

- `AGENTS.md` §12「上下文管理与开发状态持久化」：开发前必读、功能完成后的记录义务、
  任务收尾八项清单、上下文压缩后的恢复流程、核心逻辑保护、规则与执行者对照、提交粒度与可回退。
- 自动化机制：`.githooks/{pre-commit,post-commit,pre-push}`、
  `scripts/{install-hooks,session-start,status-snapshot,db-init,migrate-safe,check-docs}.sh`、
  `.github/workflows/ci.yml`、`docs/state/`（状态留痕目录）。
- `scripts/db-init.sh`：建库 → DDL → 自动 `alembic stamp`，修掉"手动建库后版本表为空"的隐患。
- `scripts/migrate-safe.sh`：迁移前自动 `pg_dump`，失败时打印回滚命令。

### 变更

- 文档结构调整：`PRD.md` `ARCHITECTURE.md` `DEVELOPMENT_PLAN.md` `PROJECT_STATUS.md` `CHANGELOG.md`
  统一移入 `docs/`；旧版过程文档移入 `docs/archive/`（`architecture-v3-passkey.md`、
  `implementation-plan-v4-node.md`、`prd-alignment.md`）。
- 本机 PostgreSQL 16.15 安装完成并验证：25 表 / 2 视图 / 37 外键 / 2 条 trgm 索引；
  `EXPLAIN` 确认命中 `ix_ingredients_name_trgm`。
- pip 安装路径统一为「优先 uv、回退镜像」，Dockerfile 增加 `PIP_INDEX_URL` 构建参数。

### 修复

- 手动执行 `database/001_init.sql` 后 `alembic_version` 为空，会让后续 `alembic upgrade head`
  重复建表并报 `relation already exists`；已 `alembic stamp 0001_init` 补齐，并纳入 `db-init.sh`。

### 验证（2026-11-09）

- **Docker 可用**：Docker Desktop 4.98.0 / 引擎 29.9.2 / Compose 5.6.1；`docker run hello-world` 通过；
  本项目 `docker compose up -d --build` 37 秒构建成功，`freshkeep-api` 与 `freshkeep-db` 均 healthy。
  `/health` → `{"status":"ok","db":true}`；容器内 `alembic current` → `0001_init (head)`；
  25 张表；`database/002_acceptance_check.sql` 8 条断言全部通过。
- **Docker CLI 修复**：原 `docker` 不在 PATH（只在 `~/.docker/bin` 与 app 包内），已向 `~/.zshrc` 追加 PATH 行，
  新开 shell 验证 `which docker` 命中 `~/.docker/bin/docker`。
- **Xcode 可用**：27.2（27B52），`xcode-select -p` 指向外接盘 `/Volumes/移动硬盘/XcodeApps/Xcode.app/Contents/Developer`；
  `/Applications/Xcode.app` 为符号链接；`-checkFirstLaunchStatus` 退出码 0；iOS 27.2 SDK 齐备；
  `xcrun swiftc` 编译并运行成功。外接卷 APFS（`noowners`、无 `noexec`、无 quarantine）→ 无权限问题。
- **发现缺口**：iOS 模拟器运行时为 0（`simctl list runtimes` 空），根卷仅剩 16 GiB，暂不下载（约 7~9 GB），
  改为真机出包路线。
- 本地生成 `.env`（随机 `POSTGRES_PASSWORD`），`docker compose config` 校验通过；`.env` 已在 `.gitignore` 中。

### 数据库

- 无 DDL 变更；新增 `alembic_version` 表（值为 `0001_init`），仅记录版本，不改变业务结构。

---

## 2026-11-08 · 阶段 0：项目准备（`ef47d78`）

### 新增

- `database/001_init.sql`：25 张表 + 2 个视图 + 37 个外键 + `updated_at` 触发器。
- `database/002_acceptance_check.sql`：PRD 三条关键用例的数据库侧断言 + 四类约束反向验证。
- `backend/`：FastAPI 装配（`/health`、`/api/v1/ping`、`x-request-id`、统一错误）、配置、会话、Alembic 0001、CLI（`pair`/`devices`/`revoke`）、pytest 冒烟 4 条。
- `frontend/`：Vue 3 + TS + Vite + Pinia 骨架，5 个视图占位，统一 API 客户端（Web Cookie / App Bearer）。
- `docker-compose.yml`（api + db）、`backend/Dockerfile`、`.env.example`、`.dockerignore`。
- `deploy/`：NAS 部署手册、`backup.sh`、`restore.sh`。
- `PRD.md`、`docs/api.md`、`docs/database.md`、`docs/er-diagram.md`、`AGENTS.md`（PRD 后在文档重整中移到根目录）。

### 数据库

- **首次建立结构**：`users` `devices` `pair_codes` `file_assets` `categories` `units` `storage_locations`
  `ingredients` `ingredient_barcodes` `nutrition_definitions` `ingredient_nutrition` `nutrition_targets`
  `batches` `inventory_transactions` `transaction_allocations` `consumption_records` `consumption_nutrition`
  `shopping_lists` `shopping_list_items` `recipes` `recipe_items` `notifications` `app_settings` `audit_logs` `idempotency_keys`。
- 视图：`v_inventory`、`v_batch_reconcile`。
- 迁移：`alembic/versions/0001_init.py`（执行 `001_init.sql`，剥掉自带 `BEGIN/COMMIT`）。
- 验证：消耗 300g → 成本 `10.80`、剩余 `42.20`、营养 `495.0000 kcal`、对账差异 0；负库存/重复分配/正 delta/孤儿快照均被拒。

---

## 2026-11-08 · 最终开发方案定稿（`9f02d60`）

### 文档

- `docs/final-plan.md`：8 处冲突全部定案——认证改为「配对码 → 长期设备令牌」（Web Cookie / App Bearer，不做密码）；
  产品形态为原生 App + Web；放弃 PWA 改用 App 本地通知；数据库 PostgreSQL 16；后端 FastAPI + 同步 SQLAlchemy；
  前端 Vue 3；双计量独立余额；批次余额为缓存 + 每日对账。
- 明确对 PRD 的 4 处必要偏离（不做密码、不做 PWA、容器 5→2、Cookie 无 Secure）及原因。

### 数据库

- 无实际变更（设计层面确定 25 表方案）。

---

## 2026-11-08 · PRD 对齐分析（`c685cf1`）

### 文档

- `docs/prd-alignment.md`：识别出 PRD 与既有方案的 8 处冲突、4 处需定死的细节；量级对比（2 表 → 25 表）；
  P0 工期重估（15.5 → 32 人日）。
- 实测环境能力：pip 可用、npm 可用、无 Docker、无 PostgreSQL。

---

## 2026-11-08 · 方案 v3（Passkey，已被取代）（`d597df7`）

### 文档

- `docs/architecture.md`：仅 Passkey 方案（WebAuthn + Tailscale sidecar + 零依赖验签）。
  该版本**已被 v4 取代**，Passkey 章节仅作技术备查。

---

## 2026-11-08 · 方案 v2（内网 + 账号密码，已被取代）（`d2cf7d2`）

### 文档

- `docs/architecture.md`：去除公网暴露、账号密码 + 会话、`ALLOW_CIDR` 白名单、参考 grocy/mealie 的建模。

---

## 2026-11-08 · 首版纯前端应用（`4823511` `f78087a` `0865189`）

### 新增

- 纯前端单页应用（`index.html` + `css/style.css` + `js/store.js` + `js/app.js` + `sw.js` + manifest）：
  库存台账、一键扣减、临期提醒、消耗统计、JSON/CSV 导出。
- `tests/selftest.html`：48 条确定性用例（日期解析、扣减边界、撤销、统计口径、CSV 转义、坏数据兜底）。
- `docs/screenshots/`：5 张移动端截图（webp）。

### 数据库

- 无（数据存浏览器 localStorage）。

> 该版本现在是**设计参考**（交互与信息架构），不是交付形态。
