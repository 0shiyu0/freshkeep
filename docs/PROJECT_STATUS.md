# 项目状态

> 快照时间：2026-11-09 02:25（Asia/Shanghai）
> 维护规则：每个里程碑结束、每次数据库结构变化、每次发现已知问题，都要更新本文与 `docs/CHANGELOG.md`。

---

## 1. 一句话现状

**M3 批次域已完成**：入库五步事务（批次 + 流水 + 分配 + 对账断言）、批次查询与临期/过期、
状态机、元数据禁改保护、前端批次区与入库表单全部落地并验证。
pytest **83 项全绿**、容器真实 HTTP **18 项断言全过**、浏览器 DOM 探针两种宽度无溢出。
本轮**无 DDL 变更**，两库迁移版本均为 `0002_ingredient_storage`。下一步是 **M4 消耗域**（风险最高）。

| 里程碑 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0 | ✅ 完成 | 文档、规则、骨架、数据库评审 |
| 阶段 1 | ✅ 完成 | 三容器 + 前后端骨架 + 日志与异常 |
| 阶段 2 | ✅ 完成 | 认证 / 分类 / 单位 / 位置 / 食材 / 图片 / 搜索 / 条码 |
| M0 骨架收尾 | ✅ 完成 | CIDR + 幂等中间件 + CI 全就位 |
| M1 认证 | ✅ | 已由阶段 2.1 交付 |
| M2 档案域 | ✅ | 已由阶段 2.2~2.8 交付 |
| **M3 批次域** | ✅ **完成** | 五步事务 / 查询 / 状态机 / 前端批次区，证据见 §2.3 |
| M4 消耗域 | ⬜ **下一步** | FEFO、成本分摊、尾差、双计量、营养快照；先写失败测试 |
| M5 库存域 | ⬜ | `v_inventory`、流水聚合、盘点、报损、对账任务 |
| M6 首页与营养 | ⬜ | dashboard、营养目标、日汇总 |
| M7 备份导出 | ⬜ | |
| M8 前端页面 | 🔄 部分 | 登录/库存/详情(含批次)/编辑/设置已完成；记录页仍是占位 |
| M9 原生 App | ⬜ | 需 Xcode（iOS 走真机自签） |
| M10 联调验收 | ⬜ | |

整体进度：**P0 完成 6/13 个里程碑（约 46%）**；按人日约 13.5/36。

---

## 2. 已完成（可验证的证据）

### 2.1 阶段 2：基础资料管理

| 模块 | 验证方式与结果 |
| --- | --- |
| 2.1 认证 | 配对码换 Cookie；密码登录返回 Bearer；退出/吊销即时失效。pytest + 浏览器内真实走完配对登录 |
| 2.2 分类 | 两级结构；同级重名 409；三级嵌套 400；有食材时删除 409；`/sort` 批量改序 |
| 2.3 单位 | 9 个内置单位；维度隔离；内置拒删 409 |
| 2.4 位置 | 冷冻室/冷藏室/常温/橱柜；被引用拒删 |
| 2.5 食材档案 | 详情页六项属性与分类标签用 DOM 探针 12 项全 true 核对 |
| 2.6 图片 | 魔数校验（非图片 415）、5MB 上限、sha256 去重、`/raw` 正确 MIME、被引用拒删 409 |
| 2.7 搜索 | `鸡`/`ji`/`jxr`/`JIXIONG` 四种输入均命中；无关词不误命中；完全匹配排首位 |
| 2.8 条码 | 查询/绑定/解绑；重复 409；未绑定 404 |

### 2.2 M0 骨架收尾

| 项 | 验证方式与结果 |
| --- | --- |
| 网段白名单 | 7 组判定矩阵：回环/局域网/组网放行，`8.8.8.8`、`1.1.1.1` 拒绝 |
| 写操作幂等 | 同 key 同 body 返回原响应 + `Idempotency-Replayed: 1`；同 key 不同 body 409；容器 curl 实测三态 |
| CI | `.github/workflows/ci.yml` 三个 job：真 PG 迁移 + 验收断言 + pytest / 前端构建 / 文档检查 |

### 2.3 M3 批次域（本轮）

| 项 | 文件 | 验证方式与结果 |
| --- | --- | --- |
| 入库五步事务 | `services/inventory/__init__.py` | `POST /batches` 同事务写批次 + `purchase` 流水 + 自分配；`Σ分配 == 流水delta == remaining_*` 断言；容器真实入库后 `v_batch_reconcile` 三个 diff 为 `0.000/0.000/0.00`，`unit_cost=0.0360` |
| 查询接口 | `api/v1/batches.py` | `GET /batches`（分页/筛选）、`/{id}`、`/expiring?days=7`、`/expired`；容器 E2E 全部 200 且数据正确 |
| 状态机 | `services/inventory/state.py` | 归零→depleted、恢复库存→active、`void` 未开放；9 项单测 |
| 元数据禁改 | `PUT /batches/{id}` | 改 `expiry_date`/`note` 200；传 `remaining_weight`/`purchase_cost`/`status` 400 |
| 单位与编号 | `core/time.py`、service | kg→克换算；`batch_no=20261109-01`、流水号递增且唯一 |
| 幂等 | 全局中间件 | 同 key 同 body 两次返回同一 id，`Idempotency-Replayed: 1`，库中只落 1 条流水 + 1 条分配 |
| 前端 | `api/batches.ts`、`IngredientDetailView.vue` | 详情页 1280/390 DOM 探针：批次区/批次号/剩余 500g/临期标签/¥18.00 全 true；「＋ 入库」弹层字段齐全；横向溢出 0px、卡片越界 0 个 |

### 2.4 测试规模

```
backend/tests/
  conftest.py              182 行   真实 PG 测试库 + 每例清库
  unit/test_pinyin.py       50 行   拼音生成 + 搜索条件（11 项）
  unit/test_batch_state.py  78 行   批次状态迁移（9 项，M3 新增）
  api/test_system.py        59 行   健康/信封/请求 id/日志上报（6 项）
  api/test_stage2.py       335 行   阶段 2 全部接口（25 项）
  api/test_middleware.py   150 行   CIDR + 幂等（14 项）
  api/test_batches.py      346 行   批次域（18 项，M3 新增）
合计 83 项，全绿
```

---

## 3. 未完成（明确列出，避免误判）

| 项 | 现状 |
| --- | --- |
| 消耗域（FEFO/成本分摊/尾差/营养快照） | 未开始，仅设计文档有伪代码；**M4 是下一步** |
| 库存域（`v_inventory` 查询、盘点、报损、撤销） | 未开始 |
| `tests/acceptance/` 层 | 尚未建立；目前库存相关 Python 断言在 `tests/api/`，M4 一并平移（AGENTS.md §12.5） |
| 首页与营养 | 首页仍是链路自检卡片，无业务数字 |
| 记录页 | `RecordsView.vue` 仍是 14 行占位（依赖流水，属 M5） |
| 配对页 | `PairView.vue` 已被 `/login` 取代，文件仍存在（可删） |
| 备份导出接口 | 未实现（脚本 `deploy/backup.sh` 可用，但无 API） |
| APScheduler 定时任务 | 依赖已装，未启用（临期扫描/对账） |
| Capacitor 原生工程 | 未 `cap add`，`android/` `ios/` 不存在 |
| NAS 部署验证 | 本机 compose 已通过；NAS 未跑过 |

---

## 4. 已知问题

| # | 问题 | 影响 | 当前处置 | 状态 |
| --- | --- | --- | --- | --- |
| K11 | 本机库与容器库曾出现迁移版本不一致 | 本机直连后端缺列 500 | 已用 `scripts/migrate-safe.sh` 迁移，回滚点 `backups/pre-migrate-freshkeep-20261109-015103.dump`；两库现均 `0002` | ✅ 已修复 |
| K12 | `session-start.sh` 只检查本机 PG，不检查容器库 | 两库版本漂移不会被自动发现 | 已知；§6 提供容器库版本核对命令 | ⚠️ 已知 |
| K9 | 无 iOS 模拟器运行时 | 不能跑 `npx cap run ios` | 根卷仅剩 16 GiB（iOS runtime 约 7~9 GB），走真机自签路线 | ⚠️ 已知 |
| K13 | `IdempotencyMiddleware` 会缓冲请求体 | 大文件上传多占一份内存 | 单用户低频操作可接受；将来支持大文件需按路径跳过 | ⚠️ 已知 |
| K14 | 幂等中间件对 `multipart/form-data` 按字节哈希 | 边界串不同被判为不同请求 | 上传接口不应带 `Idempotency-Key`；代码注释已标注 | ⚠️ 已知 |
| K15 | 批次编号用「当日计数 + 唯一约束兜底」，无并发重试 | 并发同日入库极小概率冲突 | 单用户低频可接受；M4 若引入批量入库改数据库序列 | ⚠️ 已知 |
| K16 | M3 列表响应曾多套一层 `items`，前端拿不到数组 | 批次区只显示按钮、数据不渲染 | **已修复**：与阶段 2 分页结构对齐；DOM 探针复验通过 | ✅ 已修复 |

已关闭：K1（无 Docker）、K2（PG 装不上）、K3（trgm 未验）、K4（前端未构建）、K5（无 Xcode）、
K6（旧文档冲突）、K7（无 CI）、K8（alembic 基线）、K10（容器内 npm ECONNRESET）。

---

## 5. 环境状态速查

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.13 + venv | ✅ | `backend/.venv`，pytest 83 项可用 |
| 本机 PostgreSQL | ✅ 16.15 | 库 `freshkeep` 与测试库 `freshkeep_test`，均在 `0002` |
| 容器三件套 | ✅ | `freshkeep-{db,api,web}` 全 healthy，对外 8080 |
| 容器内迁移版本 | ✅ | `0002_ingredient_storage` |
| 前端构建 | ✅ | `npm run build` 通过（vue-tsc 零错误），`dist` 02:15 生成 |
| Docker | ✅ 4.98.0 | CLI 路径已入库 `~/.zshrc` |
| Xcode | ✅ 27.2 | 外接盘；无模拟器运行时 |
| Node | ✅ 22.22 | 满足 Vite 8 / Capacitor 8 |

---

## 6. 上下文清空后如何恢复

```bash
# 0. 一条命令看全貌（推荐先跑这个）
./scripts/session-start.sh

# 1~5. 必读文档
cat AGENTS.md
cat docs/PRD.md
cat docs/ARCHITECTURE.md
cat docs/DEVELOPMENT_PLAN.md docs/PROJECT_STATUS.md
head -100 docs/CHANGELOG.md
```

**三处状态必须交叉核对**（只看一处会误判）：

```bash
git status --short && git log -3 --oneline        # 代码与提交
cd backend && .venv/bin/python -m pytest          # 期望 83 passed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps                                  # 期望 3 个 healthy
docker compose exec -T db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
psql -d freshkeep -tAc "select version_num from alembic_version"   # 两库应一致
```

---

## 7. 下一步（M4 消耗域，风险最高）

按 `docs/DEVELOPMENT_PLAN.md` 的 M4，顺序如下：

1. **先写失败测试**：`tests/acceptance/` 建立 PRD §7.1 的 9 条用例（数字不可改：
   成本 **10.80**、剩余库存成本 **42.20**、营养 **495 kcal**、FEFO A 清零 B 剩 900g）；
   把 `database/002` 的 SQL 断言同步平移成 pytest（AGENTS.md §12.5）。
2. FEFO 取批次：`ORDER BY expiry_date NULLS LAST, purchase_date, id` + `FOR UPDATE`，
   加锁顺序固定，库存不足整体回滚。
3. 消耗写入仍走五步：事务 → `consume` 流水 → 分配 → 更新批次 `remaining_*` → 断言一致；
   最后一次消耗结清尾差；多批次分摊成本之和 = 单据成本。
4. 营养快照：`consumption_nutrition` 冻结基准值，后续改档案不影响历史。
5. 撤销消耗走 `reverse` 反向流水，不删原记录；批量消耗整批成功或整批失败。
6. 前端消耗录入页与记录页（`RecordsView`）。

---

## 自动状态快照

<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 2026-11-09 02:25 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `main` / `2b722f0` |
| 工作区 | 1 个未提交改动，未跟踪 0 个 |
| 未推送提交 | 0 |
| 数据库 | 可连，迁移版本 `0002_ingredient_storage`，25 张表 |
| 后端测试 | 83 passed, 1 warning in 6.32s |
| 前端产物 | 已构建 |
| 文档检查 | 通过 |

最近 5 次提交：

```
2b722f0 2026-11-09 feat(api): M3 批次域 —— 入库五步事务、查询、状态机与前端批次区
1e575c0 2026-11-09 chore: 补齐状态留痕（commits.log）
0c37dca 2026-11-09 docs(db): 同步 ingredients.default_storage_location_id 与迁移历史
1a1e3be 2026-11-09 feat(init): 阶段 1 项目初始化 —— 三容器 + 前后端骨架 + 日志与错误处理
0d5d3ff 2026-11-09 docs: Docker 与 Xcode 环境验证结论
```
<!-- AUTO:STATUS:END -->
