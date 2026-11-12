# 备份与恢复

> 目标：任何一次误操作、升级失败、磁盘故障，都能在 10 分钟内回到一个已知可用状态。
> 恢复失败怎么退回版本见 [ROLLBACK.md](ROLLBACK.md)。

## 1. 备份有四种，用途不同

| 类型 | 产物 | 生成方式 | 适合场景 |
| --- | --- | --- | --- |
| **逻辑备份**（推荐） | `backups/freshkeep-backup-<时间戳>.tar.gz`<br>内含 `schema.sql` + 27 张表 CSV + `manifest.json` | 每天 03:10 自动；设置页「立即备份」；`POST /api/v1/backup` | 版本升级前、迁移前后、迁移到新机器 |
| **物理备份** | `*.dump`（`pg_dump -Fc` 自定义格式） | `deploy/backup.sh` | 整库快速回滚（`pg_restore` 干净） |
| **CSV 导出** | `transactions.csv` / `consumptions.csv` | `GET /api/v1/export/*.csv` | 给 Excel 分析，不用于恢复 |
| **数据目录拷贝** | 整个 `pgdata/` | `tar czf` 冷备（需停库） | 灾难恢复兜底（必须停库，否则文件不一致） |

逻辑备份是**可读、可核对、可部分恢复**的：解压后每个表一个 CSV，能直接看内容。

## 2. 升级前备份（必做）

```bash
cd /vol1/docker/freshkeep

# ① 逻辑备份（应用层一致，推荐）
docker exec freshkeep-api python - <<'PY'
from app.db.session import SessionLocal
from app.services.backup import create_backup
db = SessionLocal()
print(create_backup(db)["name"])
PY

# ② 物理备份（整库，回滚更快）
./deploy/backup.sh

# ③ 确认产物
ls -lh backups/ | tail -3
```

备份后**立刻验证可读**（这一步不做，等于没备份）：

```bash
LATEST=$(ls -t backups/freshkeep-backup-*.tar.gz | head -1)
tar tzf "$LATEST" | head -5            # 应看到 schema.sql / manifest.json / tables/*.csv
tar xzOf "$LATEST" manifest.json | head -20   # 表数与总行数
```

## 3. 自动备份

在 `ENABLE_SCHEDULER=true` 时，APScheduler 每天 **03:10** 生成逻辑备份，
并只保留最近 `BACKUP_KEEP`（默认 7）份——由 `prune_backups()` 按文件名时间戳删旧。

```bash
# 确认调度在跑
docker exec freshkeep-api python -c "
from app.tasks.scheduler import status; import json; print(json.dumps(status(), ensure_ascii=False, indent=2))"

# 手动触发一次（等同当晚任务）
curl -s -X POST http://127.0.0.1:8000/api/v1/tasks/daily_backup/run -H "Authorization: Bearer <token>"

# 看备份审计
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc \
  "select action, after_json->>'name', after_json->>'total_rows' from audit_logs where action like 'scheduler_backup%' order by created_at desc limit 5"
```

## 4. 恢复演练（不碰生产库）

`scripts/restore_drill.py` 把备份恢复到**临时库**，逐表核对行数，结束后删库：

```bash
cd /vol1/docker/freshkeep
DRILL_DB_USER=freshkeep python3 scripts/restore_drill.py \
  --psql-cmd "docker exec freshkeep-db psql -U freshkeep -d {db}" \
  --report docs/reports/restore-drill.json
```

输出 `ok: true` 且 `steps` 里 extract / create_database / restore_schema / restore_tables 全为 `true` 即通过。
**建议每次升级前后各跑一次。**

## 5. 整库恢复（灾难恢复）

⚠ 会覆盖现有数据。先停 api，避免恢复过程中被写入。

```bash
cd /vol1/docker/freshkeep

# ① 停应用（保留 db）
docker compose -f docker-compose.yml -f docker-compose.https.yml stop api web

# ② 从物理备份恢复（最快）
docker exec -i freshkeep-db pg_restore -U freshkeep -d freshkeep --clean --if-exists \
  < backups/freshkeep-<时间戳>.dump
# 或从逻辑备份恢复：解压后 psql -f schema.sql，再逐表 COPY FROM

# ③ 起服务（entrypoint 会补跑 alembic upgrade head）
docker compose -f docker-compose.yml -f docker-compose.https.yml start api web
```

## 6. 从逻辑备份恢复到新机器

```bash
# ① 新机器准备空库
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d db
docker exec freshkeep-db psql -U freshkeep -d postgres -c "DROP DATABASE IF EXISTS freshkeep"
docker exec freshkeep-db psql -U freshkeep -d postgres -c "CREATE DATABASE freshkeep"

# ② 解包
mkdir -p /tmp/restore && tar xzf backups/freshkeep-<时间戳>.tar.gz -C /tmp/restore

# ③ 建表（备份里的 schema.sql 已含 COMMIT，可直接执行）
docker cp /tmp/restore/schema.sql freshkeep-db:/tmp/schema.sql
docker exec freshkeep-db psql -U freshkeep -d freshkeep -f /tmp/schema.sql

# ④ 逐表导入（顺序按 manifest 的表清单，CSV 带表头）
for t in $(ls /tmp/restore/tables/*.csv | xargs -n1 basename | sed 's/.csv$//'); do
  docker cp /tmp/restore/tables/$t.csv freshkeep-db:/tmp/$t.csv
  docker exec freshkeep-db psql -U freshkeep -d freshkeep -c "\copy $t FROM '/tmp/$t.csv' WITH (FORMAT csv, HEADER)"
done

# ⑤ 起 api（自动迁移到最新版本）与 web
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d api web
```

## 7. 恢复后必须核对

```bash
# 表数（27 业务表 + alembic_version）
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc \
  "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"

# 关键表行数（与备份的 manifest.json 对比）
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc \
  "select 'ingredients='||count(*) from ingredients union all
   select 'batches='||count(*) from batches union all
   select 'transactions='||count(*) from inventory_transactions"

# 迁移版本
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"

# 库存一致性（差异应为 0）
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc \
  "select count(*) from v_batch_reconcile where diff_quantity<>0 or diff_weight<>0 or diff_cost<>0"
```

浏览器再走一遍：首页数字、库存列表、流水、提醒——与恢复前对比。

## 8. 保留策略与异地

- 逻辑备份保留 7 份（`BACKUP_KEEP`）；物理备份由 `deploy/backup.sh` 自行管理。
- **当前所有备份都在 NAS 同一块盘上**，盘坏则数据与备份同亡。建议至少做一条：
  - 把 `backups/` 定时 `rsync` 到另一块盘 / 另一台机器；
  - 或 `rclone sync backups/ <云盘>:freshkeep/`（备份含用户数据，云端需自行加密）。
- 备份**未加密**：`pg_dump`/CSV 都是明文。放到不受信位置前先 `age`/`gpg` 加密。

## 9. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `pg_restore: error: input file appears to be a text format dump` | 拿了逻辑备份的 tar 当 `.dump` 用 | 逻辑备份走 §6 的流程，不要用 `pg_restore` |
| `relation "xxx" does not exist` | schema 未执行或事务回滚 | 确认 `schema.sql` 末尾有 `COMMIT;`（本项目备份已自动补齐） |
| `invalid input syntax for type uuid` | CSV 列序与表不一致 | 用同版本 `schema.sql` 建表；跨大版本升级要先迁移再导数据 |
| 恢复后报 `alembic_version` 冲突 | 手工插入过版本号 | 以 `alembic upgrade head` 为准，必要时 `alembic stamp head` |
| 备份文件 0 字节 | 备份时磁盘满或进程被杀 | 检查 `df -h`；重新生成并 `tar tzf` 验证 |
