# 阶段 9 · 备份与恢复演练记录

> 演练脚本：`scripts/restore_drill.py`；机器可读结果：`docs/reports/restore-drill.json`。
> 演练库名 `freshkeep_drill_<时间戳>`，**不触碰生产库**，结束后必定 DROP。

## 演练口径

1. 取最新逻辑备份 `freshkeep-backup-*.tar.gz`；
2. 校验 tar 内路径安全（拒绝绝对路径与 `..`）；
3. 建临时库 → `psql -f schema.sql` → 逐表 `\copy ... WITH (FORMAT csv, HEADER)`；
4. 逐表 `COUNT(*)` 与 `manifest.json` 比对，并抽查 ingredients / batches / inventory_transactions；
5. DROP 演练库，输出 JSON 报告。

## 第一次演练（本机）

| 项 | 结果 |
| --- | --- |
| 备份 | `freshkeep-backup-20261111-165719.tar.gz`（M7 阶段在容器内生成） |
| 结果 | **失败** |
| 原因 1 | 备份内 `schema.sql` 只有占位文本 `-- schema.sql 缺失` |
| 根因 | `services/backup.py` 用 `parents[3]` 定位 `database/001_init.sql`，容器内实际在 `/app/database`，路径算错 |
| 原因 2 | `001_init.sql` 以 `BEGIN;` 开头但没有 `COMMIT;`，`psql -f` 会话结束回滚，27 张表全部消失 |
| 表现 | 逐表 `COPY` 报 `relation "users" does not exist` |

## 修复

- `services/backup.py`：多候选路径探测（本机 repo / 容器 `/app/database`），找不到就抛错，不再静默产出坏备份；
  写入 tar 前若检测到 `BEGIN;` 且无 `COMMIT;` 则自动补齐，保证备份自带可执行 schema。
- `scripts/restore_drill.py`：识别占位 schema 直接失败；执行前补 `COMMIT` 兜底；
  恢复 schema 后校验「至少建出 20 张基表」，避免把「假成功」当成演练通过。
- `prune_backups(keep=7)`：保留最近 7 份，防止备份无限增长。

## 第二次演练（本机，修复后备份）

| 项 | 结果 |
| --- | --- |
| 备份 | `freshkeep-backup-20261111-183620.tar.gz`（27 表 / 0 行，本机库为空） |
| extract | ✅ 27 个 CSV |
| create_database | ✅ |
| restore_schema | ✅ 27 张基表 |
| restore_tables | ✅ 27 表逐表行数一致 |
| 抽查 | ingredients / batches / inventory_transactions 均可查询 |
| 结论 | **`ok=true`**（结构恢复链路验证通过） |

本机库无业务数据，因此用 NAS 部署完成后的备份再做一次**带数据**的演练，结果记录在下一节。

## 第三次演练（NAS 部署完成后，带真实数据）

| 项 | 结果 |
| --- | --- |
| 备份 | `freshkeep-backup-20261111-190543.tar.gz`（27 表 / 43 行 / 11521 字节） |
| extract | ✅ 27 个 CSV |
| create_database | ✅ |
| restore_schema | ✅ 27 张基表 |
| restore_tables | ✅ 27 表逐表行数一致（含演练数据：ingredients 1、batches 1、transactions 1） |
| 抽查 | {"ingredients": "1", "batches": "1", "inventory_transactions": "1"} |
| 结论 | **`ok=true`** |

## 结论

恢复链路（tar → schema → 27 表 COPY → 校验 → 清理）在本机与 NAS 上各验证通过；
第一次演练暴露的 schema 路径与 COMMIT 两个缺陷已修复并有回归测试覆盖。
