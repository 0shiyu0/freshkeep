# 路由入参校验一致性审计

> 审计时间：2026-11-12 · 范围：`backend/app/api/v1/` 全部 22 个文件、**85 条路径**
> 结论：发现 **2 处实际缺陷（已整改）**、3 类"有意不分页"的端点（已确认合理）。

## 1. 统一规范（本次确认，后续新增端点需遵守）

| 维度 | 规范 | 检查方式 |
| --- | --- | --- |
| 路由文件职责 | 只做参数校验 → 调 service → `ok(request, data, msg)` 包装 | 全库 `ok(request` 用法 86 处，无手写 `{"data": ...}` |
| 响应信封 | 统一 `{"success", "data", "message", "request_id"}` | 由 `schemas/common.ok()` 生成 |
| 路径 ID | 一律 `uuid.UUID` 类型注解（FastAPI 自动 422） | 除 `job_id`（枚举）、`kind`（白名单）、`name`（文件名） |
| 列表分页 | `page: int = Query(default=1, ge=1)`、`page_size: int = Query(default=20, ge=1, le=100)` | 见 §3 |
| 排序 | `sort_by` / `sort_order` 用 `Query(pattern=...)` 白名单，禁止直接拼 SQL | 见 §4 |
| 请求体 | 一律 Pydantic `*In` 模型，禁止裸 `dict` | 全库 0 处 `payload: dict` |
| 错误码 | 业务错误走 `ApiError(code, msg, status)`；校验错误由全局 handler 统一转 400 + `VALIDATION_ERROR` | `main.py:158` |

## 2. 逐文件审计结果

| 文件 | 端点数 | 分页 | 入参校验 | 备注 |
| --- | --- | --- | --- | --- |
| `ai.py` | 7 | — | Pydantic In + UUID path | 识别草稿：`PATCH` 只允许白名单字段 |
| `alerts.py` | 5 | ✅ 2 处 | UUID + Query | `days` 有 `ge/le` 约束 |
| `auth.py` | 9 | — | 配对码字符串 + 设备名长度 | 设备列表不分页（单用户 ≤10 台，合理） |
| `backup.py` | 7 | — | ⚠️ 见 §3-② | 备份列表不分页（保留 7 份，合理） |
| `barcodes.py` | 3 | — | 条码字符串 `min_length` | 单条查询，不涉及列表 |
| `batches.py` | 6 | ✅ 2 处 | UUID + 日期 + Decimal | 金额/重量走 `Decimal` |
| `categories.py` | 5 | — | Pydantic In | 字典表（<50 条），不分页合理 |
| `consumptions.py` | 5 | ✅ 2 处 | UUID + 日期范围 | 日期起点/终点有先后校验 |
| `dashboard.py` | 2 | — | `period` 白名单 | 固定周期枚举 |
| `files.py` | 4 | — | 文件 MIME + 大小限制 | 单文件操作 |
| `ingredients.py` | 9 | ✅（整改后） | ⚠️ 见 §3-① | 搜索 `q` 有长度上限 |
| `inventory.py` | 9 | ✅ 4 处 | UUID + 状态枚举 | 盘点/报损走 Pydantic In |
| `nutrition.py` | 3 | — | Pydantic In | 项目/档案版本，数量少 |
| `products.py` | 3 | — | 条码字符串 + SSRF 防护 | 外部源地址拒绝内网 |
| `purchase.py` | 1 | — | 复用批次 In | — |
| `recipes.py` | 6 | ✅ 2 处 | UUID + `servings` `gt=0` | 匹配按份数缩放 |
| `shopping.py` | 7 | ✅ 2 处 | UUID + Pydantic In | 含 `import`（一键入库） |
| `stats.py` | 1 | — | `range` 白名单 | 固定区间 |
| `system.py` | 4 | — | 无入参 | 健康/版本/DB 结构 |
| `units.py` | 0+3 | — | Pydantic In | 字典表，不分页合理 |
| `router.py` / `__init__.py` | 0 | — | — | 仅聚合 |

## 3. 发现的问题与整改

### ① `ingredients.list_ingredients` 分页参数无上界（已整改）

| 项 | 内容 |
| --- | --- |
| 问题 | `page: int = 1`、`page_size: int = 20` 是裸默认值，**没有 `ge/le` 约束**；`sort_by` / `sort_order` 是任意字符串 |
| 风险 | `page_size=100000` 可一次拉全表（家庭数据量小，暂不致命，但与其它路由不一致，且将来数据变多会拖垮 DB）；`sort_by` 若被直接拼进 SQL 会有注入面 |
| 整改 | 改为 `Query(default=1, ge=1)`、`Query(default=20, ge=1, le=100)`；`sort_by` 限定 `^(updated_at|name|created_at)$`，`sort_order` 限定 `^(asc|desc)$` |

### ② `backup.run_task` 的 `job_id` 无约束（已整改）

| 项 | 内容 |
| --- | --- |
| 问题 | `job_id: str`，任意值进入 service 后才由 `run_now()` 抛 `ValueError` → 转为 400 |
| 风险 | 非法值产生无意义的服务调用与日志噪音；错误信息依赖 service 内部实现 |
| 整改 | 改为 `job_id: Literal["daily_reconcile", "daily_backup", "expiring_scan"]`，由框架在入口校验；响应码仍是 400（项目全局 handler 把校验错误统一为 400 + `VALIDATION_ERROR`） |

### ③ 三类"有意不分页"（确认合理，不做改动）

| 端点 | 为何不分页 | 上限保障 |
| --- | --- | --- |
| `/categories`、`/units`、`/storage-locations` | 家庭字典表，各 < 50 条 | 有唯一名约束，实际增长极慢 |
| `/auth/devices` | 个人设备数 ≤ 10 | 配对时有设备注册逻辑 |
| `/backups` | 只保留最近 `BACKUP_KEEP`（默认 7）份 | `prune_backups()` 主动删旧 |

## 4. 仍存在的弱点（未整改，记录在案）

| # | 项 | 说明 | 影响 |
| --- | --- | --- | --- |
| 1 | 搜索参数 `q` 只限长度，不限制通配符 | `ILIKE '%...%'` 由参数化查询承载，无注入风险，但极端长的 `q` 会拖慢模糊搜索 | 低（参数化 + 长度上限） |
| 2 | `sort_by` 白名单靠枚举维护 | 新增可排序字段时要同步改正则 | 低（改一处） |
| 3 | 部分列表端点未返回 `total_pages` | 前端按 `total + page_size` 自行计算 | 无 |
| 4 | `files` 上传只校验 MIME 与大小，不校验内容魔数 | 图片会再经前端 `img` 解码 | 低（自托管单用户） |

## 5. 复现审计

```bash
cd backend

# 列表端点的分页参数
grep -rn "page: int\|page_size: int" app/api/v1/*.py | sed 's/^/  /'

# 是否有裸 dict 入参
grep -rn "payload: dict\|body: dict" app/api/v1/*.py || echo "  无"

# 路径 ID 是否都是 UUID
grep -rn "id: str" app/api/v1/*.py || echo "  无（除 job_id 枚举）"

# 统一响应包装的覆盖度
grep -c "return ok(request" app/api/v1/*.py | awk -F: '{s+=$2} END {print "  ok() 调用:", s}'
```

整改后：`ruff check app` 全过；`pytest` **232 passed**，覆盖率 **87%**（门槛 80%）。
