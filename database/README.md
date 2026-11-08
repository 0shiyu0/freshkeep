# database/

DDL 与数据库侧自检脚本。

| 文件 | 用途 |
| --- | --- |
| `001_init.sql` | **数据库结构的唯一真相**。建 25 张表 + 2 个视图 + 索引/约束/触发器 |
| `002_acceptance_check.sql` | 在真库上跑 PRD 的 3 条关键用例（成本 10.80 / 42.20、FEFO、营养快照），并验证负库存与重复分配被拒 |

## 本地重建

```bash
brew services start postgresql@16
createdb freshkeep
psql -d freshkeep -f database/001_init.sql
psql -d freshkeep -f database/002_acceptance_check.sql
```

`002` 期望输出：

```
NOTICE:  用例1（批次成本）通过：成本 10.80 / 批次1 剩 200g·7.20 / 合计 42.20
NOTICE:  用例3（营养快照）通过：300g × 165kcal/100g = 495 kcal
NOTICE:  用例2（FEFO）通过：A 清零、B 剩 900g
NOTICE:  对账视图通过：三个 diff 均为 0
NOTICE:  约束通过：remaining_weight 负值被 CHECK 拒绝
NOTICE:  约束通过：(transaction_id, batch_id) 重复分配被拒
NOTICE:  === 全部验收用例通过 ===
```

脚本最后 `ROLLBACK`，不会把测试数据留在库里。

## 容器内

`api` 容器的入口脚本会执行 `alembic upgrade head`，而 `0001_init` 迁移就是执行本目录的 `001_init.sql`：

```bash
docker compose exec api alembic current     # 查看当前版本
docker compose exec api alembic upgrade head
```

## 改表结构的顺序

1. 改 `001_init.sql`；
2. 本地重建库并跑 `002`；
3. 同步 `docs/database.md` 与 `docs/er-diagram.md`；
4. 需要新迁移时新增 `backend/alembic/versions/000N_*.py`（只登记版本，不手写 DDL）。
