# 成本核算测试报告（阶段 4 · 库存引擎）

> 生成时间：2026-11-10 17:30（Asia/Shanghai）
> 报告口径：**只记录实际运行输出**，数字来自 `pytest` 与两个独立脚本的实跑结果，不含推测值。
> 关联文档：`docs/PRD.md §5.2 / §7.1`、`docs/ARCHITECTURE.md §7.1~7.2`、`docs/CHANGELOG.md`。

---

## 1. 被测对象与范围

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 纯计算层（本阶段新增） | `backend/app/services/inventory/engine.py` | FEFO 排序、扣减计划、成本分摊、尾差结清、双计量比例、流水重算、对账差异判定；**无 IO** |
| 事务编排层 | `backend/app/services/consumption/`、`services/inventory/ops.py` | 行锁、事务、写流水/分配、更新缓存、一致性断言 |
| 成本相关接口 | `POST /consumptions`、`/consumptions/batch`、`/inventory/adjustments`、`/inventory/spoilage`、`POST /consumptions/{id}/reverse` | 成本写入与撤销 |

成本核算规则（与 AGENTS.md 一致）：

1. 单位成本 = 批次剩余成本 ÷ 批次剩余量（重量或数量），精度 4 位；
2. 非整批扣减：`成本 = 扣减量 × 单位成本`，四舍五入到分；
3. **整批扣完**：成本直接取剩余成本（尾差结清），保证批次成本归零而不是残留 0.01；
4. 单据成本 = 各批次分摊成本之和；
5. 全程 `Decimal`，禁止 `float`。

---

## 2. 执行环境

```
日期        2026-11-10
数据库      PostgreSQL 16.15（容器 freshkeep-db）
后端        Python 3.13 / FastAPI / SQLAlchemy 2.1 / psycopg 3
测试框架    pytest 9.x
全量结果    140 passed, 1 warning in 5.48s
```

---

## 3. A 段：引擎纯函数实测（不依赖数据库）

命令：`cd backend && .venv/bin/python /tmp/cost_evidence.py`（脚本直接导入 engine）

```
单批次部分扣减 300/500g，18 元
  b1: 扣 300.000g 成本 10.80元 单位成本 0.0360 扣完=False
  单据成本合计 = 10.80 元
尾差：整批扣完 300/300g，10 元
  b1: 扣 300.000g 成本 10.00元 单位成本 0.0333 扣完=True
  单据成本合计 = 10.00 元
多批次：A500/18 + B1000/35，扣 600
  A: 扣 500.000g 成本 18.00元 单位成本 0.0360 扣完=True
  B: 扣 100.000g 成本 3.50元 单位成本 0.0350 扣完=False
  单据成本合计 = 21.50 元
```

关键结论：

- 单位成本 0.0360 与 18 ÷ 500 一致；
- **尾差场景**：300g 批次成本 10.00 元，按单位成本乘会得到 9.99（0.0333 × 300），
  引擎按「扣完取剩余成本」输出 **10.00**，差 1 分被正确结清；
- 多批次：18.00（A 扣完，取剩余成本）+ 3.50（B 按 0.0350 × 100）= **21.50**，
  且等于各分摊之和。

---

## 4. B 段：真实 HTTP + 真实数据库

命令：同一脚本的 B 段，通过 `POST /consumptions` 走完整链路。

```
消耗 300g → 单据成本 10.80 元
  批次 20261110-01: -300.000g / -10.80元 / 单位成本 0.0360
剩余批次： 20261110-01=200.000g/7.20元 | 20261110-02=1000.000g/35.00元
剩余库存成本： 42.20 元
对账差异条数： 0
```

与 PRD §7.1 第 1 条的验收数字逐项一致：

| 断言项 | PRD 期望 | 实测 |
| --- | --- | --- |
| 消耗成本 | 10.80 | **10.80** |
| 批次 1 剩余 | 200g / 7.20 元 | **200.000g / 7.20 元** |
| 批次 2 剩余 | 1000g / 35.00 元 | **1000.000g / 35.00 元** |
| 剩余库存总成本 | 42.20 | **42.20** |
| 对账差异 | 0 | **0 条** |

---

## 5. 8 项必须测试的实际结果

文件：`backend/tests/acceptance/test_stage4_engine.py`（10 项，含 4.1/4.12）

| # | 用例 | 断言要点 | 结果 |
| --- | --- | --- | --- |
| 1 | 消耗 300g 正确分配批次 | 只分配到期更早的批次；-300.000g / -10.80 元；B1 剩 200g/7.20 | ✅ |
| 2 | 库存不足整笔失败 | 422 `INSUFFICIENT_STOCK`；`type='consume'` 流水数 0；余额不变 | ✅ |
| 3 | 批量一项失败全部回滚 | 422；`consumption_records` 0 条；两个食材余额均为原值 | ✅ |
| 4 | 两次并发不出负库存 | 两线程同扣 400g/500g → `[201, 422]`；余额 100g ≥ 0 | ✅ |
| 5 | 撤销通过反向流水恢复 | 流水序列 `purchase → consume → reverse`；余额回 1000g；原单 `reversed` | ✅ |
| 6 | 批次归零剩余成本归零 | 300g/10 元整批扣完 → 余额 0、成本 **0.00**、状态 `depleted` | ✅ |
| 7 | 重复提交不重复扣库存 | 同 key 三次只 1 条消耗单；余额 900g | ✅ |
| 8 | 手动调整生成调整流水 | `type='adjustment'`、-20.000g、-0.72 元、原因落库 | ✅ |
| 9 | 4.1 流水口径库存 | `ledger_weight=1200.000`、`cached_weight=1200.000`、`consistency=ok` | ✅ |
| 10 | 4.12 对账发现并修复 | 篡改缓存 -5g 后差异 `-5.000`；修复后回 500.000；写 `audit_logs` | ✅ |

引擎纯函数单测：`backend/tests/unit/test_inventory_engine.py`，**17 项全绿**，覆盖：

- FEFO 排序（到期早优先、无到期日排最后、同到期日按购买日）；
- 跨批次扣减与 `closes_batch` 标记；
- 部分扣减四舍五入到分（3.33）；
- 尾差结清（10.00 而非 9.99）；
- 成本为 0 的批次不除零；
- 单据成本 = 分摊之和；
- 库存不足抛错并携带 required/available/shortage；
- 数量模式与重量模式的双计量比例换算；
- 流水重算（含反向流水回到初始值、负余额钳零）；
- 对账差异精确比较（1 毫克也算差异）。

---

## 6. 拒绝与边界场景

| 场景 | 行为 | 证据 |
| --- | --- | --- |
| 消耗量 > 可用量 | 422 `INSUFFICIENT_STOCK`，`details` 含 required/available/shortage | acceptance 用例 2 |
| 批量中一项不足 | 整批回滚，无部分流水 | 用例 3 |
| 并发同扣 | 行锁 `FOR UPDATE OF batches`，后到者 422 | 用例 4；去掉锁后该用例变红（已做过反向验证） |
| 双计量不自洽 | 422 `INCONSISTENT_MEASURE` | `test_consumption.py::test_8_unit_mismatch` |
| 无换算关系要求换算 | 422 `UNIT_NOT_CONVERTIBLE` | 同上 |
| 批次缓存被篡改 | 对账接口列出差异；修复写审计 | 用例 10 |

---

## 7. 复现方式

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_inventory_engine.py        # 17 passed
.venv/bin/python -m pytest tests/acceptance/test_stage4_engine.py     # 10 passed
.venv/bin/python -m pytest                                            # 140 passed

# 成本数字（需要容器与种子数据）
.venv/bin/python /tmp/cost_evidence.py   # A 段纯函数 + B 段真实 HTTP
```

---

## 8. 已知边界

1. **尾差只在「整批扣完」时结清**：部分扣减累计到最后一笔才归零，这是 PRD §5.2 的设计；
   若用户永不扣完而直接盘点为 0，走盘点路径同样会结清（`test_adjustment_to_zero_clears_cost`）。
2. **盘盈会改动初始量**：为满足 `remaining <= initial` 约束，盘盈时上调 `initial_*` 与
   `purchase_cost`，历史「初始量」不再是最初入库值（详见 `PROJECT_STATUS.md` K22）。
3. **成本核算只按主维度**：同时改数量与重量时按重量计成本，数量差异不单独计价（K20）。
4. **营养快照不参与成本**：营养值只做展示与摄入估算，不影响金额。
