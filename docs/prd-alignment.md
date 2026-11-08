# PRD V1.0 对齐分析：差异、冲突与修订计划

> ⚠️ **已被 `docs/final-plan.md` 取代**：本文是冲突识别的过程文档（8 处冲突在此首次列出）。
> 冲突的最终决策、对 PRD 的 4 处必要偏离、以及完整实施方案，以 `docs/final-plan.md` 为准。
> 本文保留作决策溯源，其中的技术选型（如"认证双通道"）已被否定。

> 输入：`家庭食材库存与营养管理系统_PRD及技术设计_V1.0.docx`（193 段、9 张表、22 张库表设计、约 60 个接口）
> 对照：`docs/implementation-plan.md`（Node + SQLite + 原生 JS + Capacitor）
> 结论：**以 PRD 为准。这是一次"换产品"，不是"补功能"。**

---

## 0. 三句话结论

1. **范围量级变了**：从「食材一行 + 消耗流水」变成「档案 / 批次 / 双计量 / 成本分摊 / 营养快照 / 菜谱 / 采购清单」，
   22 张表、约 60 个接口，P0 本身就包含成本核算与营养基础。
2. **技术栈随 PRD**：FastAPI + SQLAlchemy 2 + Pydantic + PostgreSQL + Alembic + APScheduler；
   Vue 3 + TS + Vite + Pinia + ECharts。我前几轮的 Node / SQLite / 原生 JS 在**存储与框架层作废**。
3. **可复用的部分**：业务规则（FEFO、幂等、事务边界、撤销语义、统计双口径）与验证方法（自检用例、数字核对）
   全部可平移；现有原生 WebUI 降级为"视觉与信息架构参考"，代码不复用。

---

## 1. 量级对比

| 维度 | 既有方案 | PRD V1.0 | 影响 |
| --- | --- | --- | --- |
| 数据模型 | 2 张表（items / logs） | **22 张表** | 数据层全重写 |
| 核心概念 | 食材即一行 | **档案 vs 批次分离**（"是什么"与"哪一次买的"） | 前端 5 页全部重做 |
| 计量 | 单单位 + 换算系数 | **数量 + 重量双计量**，有换算关系才联动 | 每个输入/展示都是双值 |
| 成本 | 无 | 批次成本 + FEFO 分摊 + 尾差结清 | **新增核心模块** |
| 营养 | 无 | 档案（含基准量）+ 消耗时快照 + 目标 | **新增核心模块** |
| 接口 | ~15 个 | ~60 个 | 3~4 倍 |
| 认证 | 配对码 | §9 写密码哈希 + `users.password_hash` + `/auth/change-password` | **冲突（见 §2-1）** |
| 前端 | 原生 JS 无构建 | Vue 3 + TS + Vite + Pinia + 组件库 + ECharts | 全部重写 |
| 数据库 | SQLite（内置驱动） | PostgreSQL | 见 §2-4 |

---

## 2. 八处冲突与处理

| # | 冲突点 | PRD 的写法 | 既有方案 | 处理建议 |
| --- | --- | --- | --- | --- |
| 1 | **认证形态** | §9「密码用 Argon2id 或 bcrypt」；`users.password_hash`；`/auth/login`、`/auth/change-password` | 上一轮已定**配对码**（无账号密码） | **双通道**：`users.password_hash` 建字段（可空），auth 模块同时挂 `/auth/pair` 与 `/auth/login`。多约 0.5 人日，但两边都成立——PRD 的改密接口有落脚处，你定的配对码也保留。只留配对码则 `change-password` 无处实现；只留密码则新设备接入要打键盘 |
| 2 | **产品形态** | PWA，手机优先，同时适配电脑浏览器 | 原生 App（Android APK + iOS 自签 IPA） | **PWA 为主**，原生壳降级 P2 可选。PRD 的 5 个导航页用 PWA 完全够；原生壳的维护成本（IPA 签名链、重签、掉签）与收益不成比例。原 App 需求可在 P2 用 Capacitor 包一层，不动业务代码 |
| 3 | **PWA 与 HTTP 的冲突** | §4.8/§9 要 PWA 安装与系统通知，同时自己写明"启用 HTTPS 后再开放 PWA 能力" | 配对码方案走 `http://IP:8080` | Service Worker 与 Notification **都要求安全上下文**，HTTP 下不可用（已实测：局域网 IP 上 `navigator.credentials` 都不存在，SW 同理）。**P0 做响应式 Web，P1 上局域网自签 CA + Caddy 后再开 PWA**。方向与 PRD §9 一致 |
| 4 | **数据库** | 建议 PostgreSQL：金额 `NUMERIC(14,2)`、重量 `NUMERIC(14,3)`、UTC `TIMESTAMPTZ` | SQLite（`REAL`） | **按 PRD 用 PG**。决定性理由：核心验收用例就是「消耗成本 10.80 元 / 剩余 42.20 元」，SQLite 没有真十进制类型，`REAL` 浮点误差会直接让验收不过；再加上批次行级锁、视图、对账任务，PG 更合适。代价是 NAS 多一个容器（约 150 MB 内存） |
| 5 | **后端语言** | FastAPI + SQLAlchemy 2 + Pydantic | Node + 原生 `http` | **按 PRD 用 Python**。补充实测：本机 pip 可用（已下载 fastapi）、npm 可用，两条路都能本地开发；但本项目的重活是"多表事务 + 强校验 + 定时任务"，正是 SQLAlchemy/Pydantic/APScheduler 的强项 |
| 6 | **前端框架** | Vue 3 + TS + Vite + Pinia + Naive UI/Element Plus + ECharts | 原生 JS、无构建 | **按 PRD**。原原生版保留为交互参考（信息架构已在真机上验过），不复用代码 |
| 7 | **计量模型** | 数量与重量双维度，独立余额 | 单维 `qty` + `base_factor` | **按 PRD**。原 `base_factor` 可映射为 PRD 的 `default_unit_weight`，但要扩成两个独立余额与两个 delta 字段 |
| 8 | **库存真值** | 余额 = 初始 + 流水变化之和；批次余额是**可重算缓存** | `items.qty` 是唯一真值 | **按 PRD**。需要额外提供"对账/重算"任务，把缓存与流水对齐（这也是 PRD §6 的要求） |

---

## 3. PRD 内部需要定死的 4 个细节

| # | 位置 | 问题 | 建议 |
| --- | --- | --- | --- |
| 1 | §4.3 与 §12 | 档案里有"营养数据来源"，§12 又列"营养数据来源优先级待明确" | V1 只支持**手动录入**；"包装营养表拍照识别"随 P2 的 AI 一起做；不接第三方食品数据库（数据质量与合规都不可控） |
| 2 | §5.2 | "最后一次消耗结清尾差"——"最后一次"如何判定 | 定为：**同一批次本次扣完**（`take == remaining_weight`）时，成本直接取 `remaining_cost`，并把 `remaining_cost` 置 0。判定放在分配循环内，天然幂等 |
| 3 | §4.5 与 §4.6 | "禁止负库存"与"盘点调整"的边界 | 盘点只允许把余额调到 `≥ 0`；`inventory_transactions` 上加 `CHECK (remaining >= 0)` 的等价约束由服务层保证（跨表，用触发器或事务内校验） |
| 4 | §6 | 提到"建议增加视图"，未定义字段 | 固定一个 `v_inventory` 视图：`ingredient_id, total_quantity, total_weight, total_cost, batch_count, nearest_expiry, is_low_stock`。首页、库存页、采购建议全部只读这个视图，避免三处各写一遍聚合 SQL |

---

## 4. 本机可验证性（实测，不是推测）

| 能力 | 状态 | 对开发的影响 |
| --- | --- | --- |
| `pip install` | ✅ 可用（`fastapi` 已成功下载） | 后端可本地开发、跑 pytest |
| `npm install` | ✅ 可用（`npm view vue version` → 3.5.45） | Vue + Vite 可本地构建 |
| Docker | ❌ 未安装 | **无法本地验证 compose**，只能在 NAS 上验；因此 compose 与 Dockerfile 要极简，并附逐条自检清单 |
| PostgreSQL | ❌ 未安装（有 Homebrew 7.0.9） | 需 `brew install postgresql@16` 才能本地跑集成测试；否则只能用 SQLite 跑，**会掩盖 NUMERIC 精度与并发差异** |

**开发策略**：本地装一次 PG（一次性投入约 5 分钟），单元测试与集成测试都在真 PG 上跑；
compose 相关只做静态审阅，交付时给 NAS 上的验证步骤清单。

---

## 5. P0（V1.0）工期重估

按 PRD 表 164 的 P0 范围：登录、分类、食材档案、批次、库存、数量/重量、消耗、流水、成本、首页、营养基础、备份。
（临期提醒、盘点、报损、撤销、统计、导出属 P1，不在下表。）

| 模块 | 内容 | 人日 |
| --- | --- | --- |
| 地基 | docker-compose（api/db/web）+ Alembic + 统一响应/错误码 + 幂等中间件 + request_id | 3 |
| 认证 | users 表、密码哈希、配对码、会话 Cookie、登录限流 | 1.5 |
| 档案域 | 分类、单位、食材、条码、储存位置、图片资源 | 3 |
| 批次域 | 入库、批次查询、批次详情、状态机 | 4 |
| 消耗域 | FEFO 分配、成本分摊与尾差、双计量联动、事务、营养快照 | 5 |
| 库存域 | `v_inventory`、余额、流水列表、食材详情聚合 | 3 |
| 首页与营养 | dashboard 四组接口、营养定义/档案/目标、日汇总 | 3 |
| 备份导出 | 数据库+文件备份、完整性校验、导出 CSV/JSON | 1.5 |
| 前端 | 登录、首页、库存、记录、设置 5 页（Vue 3 + TS + Pinia + ECharts） | 6 |
| 联调与验收 | 9 条验收用例跑绿、时区与边界用例 | 2 |
| **合计** | | **≈ 32 人日** |

对比上一版估算（15.5 人日）翻倍：因为 PRD 的 P0 就含成本核算与营养，原方案这两块完全不存在。
P1（提醒/盘点/报损/撤销/统计/导出/扫码，约 10 人日）、P2（AI 识别/采购清单/菜谱/PWA 通知，约 12 人日）另计。

---

## 6. 最容易做错的三处（实现要点）

### 6.1 FEFO 分配

```python
# 排序：有到期日的按到期日升序；无到期日的排最后；同到期日按入库时间
batches = db.query(Batch).filter(
    Batch.ingredient_id == iid, Batch.remaining_weight > 0, Batch.status == 'active'
).order_by(Batch.expiry_date.asc().nulls_last(),
           Batch.purchase_date.asc(), Batch.id.asc())

need = request_weight
allocations = []
for b in batches:
    if need <= 0: break
    take = min(b.remaining_weight, need)
    cost = b.remaining_cost if take == b.remaining_weight \
           else round(take * (b.remaining_cost / b.remaining_weight), 2)
    allocations.append((b, take, cost))
    need -= take
if need > 0:
    raise InsufficientStock(...)   # 整单回滚，不产生任何部分流水
```

三个边界：① `remaining_weight == 0` 的批次必须被过滤（否则除零）；② 浮点/十进制比较一律用 `Decimal`，
不要用 `float`；③ 分配结果写入 `transaction_allocations`，这是撤销与对账的唯一依据。

### 6.2 成本分摊与尾差

- 单位成本 = `remaining_cost / remaining_weight`，**每次分配时实时算**，不要缓存到批次上（缓存会漂）。
- 尾差：扣完即取 `remaining_cost`，把批次剩余成本置 0，避免"库存归零仍残留 0.01 元"。
- 多批次 = 各批次分摊之和；单据级 `cost_delta` 必须等于各 allocation 之和（事务内断言，失败回滚）。

### 6.3 双计量与"拒绝自动换算"

规则：`default_unit_weight` 为空 → **禁止**任何数量↔重量自动换算，请求里带另一个维度直接 `VALIDATION_ERROR`；
非空 → 只填一个维度时按换算补齐，另一维度标记 `derived=true` 并存进流水备注。
两条都要写进校验层（Pydantic validator），而不是散落在业务函数里。

### 6.4 幂等

`Idempotency-Key` 请求头 → `idempotency_keys(key, request_hash, response_json, created_at)`。
同 key + 同 body 哈希 → 直接返回原响应；同 key + 不同 body → `DUPLICATE_REQUEST`。
比"靠业务规则去重"可靠，且能覆盖网络重试导致的重复入库。

---

## 7. 验收用例：PRD 的数字我核过，可直接当测试

| 用例 | 核对 |
| --- | --- |
| 批次1 500g/18元，批次2 1000g/35元，消耗 300g | 单价 0.036 元/g → 300g = **10.80 元** ✓；剩 200g = 7.20 元，批次2 = 35.00 元，合计 **42.20 元** ✓ |
| FEFO：A 500g(11-10)、B 1000g(11-20)，消耗 600g | A 清零、B 剩 900g ✓ |
| 营养 165kcal/31g蛋白/3.6g脂肪 每 100g，消耗 200g | 330kcal / 62g / 7.2g ✓ |
| 库存不足 / 重复请求 / 并发扣减 / 撤销 / 单位不匹配 / 批量回滚 | 6 条都对应明确的 HTTP 错误码与事务行为 |

这 9 条建议直接落成 `tests/acceptance/` 下的 pytest 用例，先写红再写绿——它们是整个 P0 的验收基线。

---

## 8. P0 内部的开工顺序

1. 骨架：`docker-compose` + Alembic 首版迁移 + `/health` + 统一响应 + 幂等中间件（**先跑通，后面所有接口复用**）
2. 认证：密码 + 配对码双通道（本地可旁路，便于后续调试）
3. 档案域：分类 → 单位 → 食材 → 条码 → 位置
4. 批次域：入库即建批次，验证"同一食材多批次互不覆盖"
5. **消耗域**：先把 §7 的 9 条用例写成失败测试，再实现到全绿（这是全项目风险最高的一块）
6. 库存域 + 首页 + 营养基础
7. 备份导出
8. 前端 5 页接 API
9. P1：临期提醒、盘点、报损、撤销、统计、导出、扫码

---

## 9. 三个我按默认拍板的决定

| 决定 | 取值 | 若要改回 |
| --- | --- | --- |
| 认证 | **密码 + 配对码双通道**，`users.password_hash` 用 Argon2id | 删 `/auth/pair` 与 `pair_codes` 表即退回纯密码；删 `/auth/login` 即退回纯配对码 |
| 数据库 | **PostgreSQL 16**，金额 `NUMERIC(14,2)`、重量 `NUMERIC(14,3)` | 换 SQLite 需把所有金额/重量改成整数（分/毫克）存储，业务代码大量改动，不建议 |
| 前端 | **Vue 3 + TS + Vite + Pinia + ECharts** | 无（PRD 指定） |

---

## 10. 与既有文档的关系

| 文档 | 状态 |
| --- | --- |
| 本文 | **PRD 对齐与冲突处理的唯一依据** |
| `docs/implementation-plan.md` | 功能拆解思路可参考，但**技术栈与数据模型已被本文取代** |
| `docs/architecture.md` | 容器化思路、IP 直连、iOS 打包自签、备份排障仍有效；认证与数据模型章节作废 |
| 现有 `index.html` + `js/*` | 保留为纯前端演示版；同时作为新前端的**视觉与交互参考** |
