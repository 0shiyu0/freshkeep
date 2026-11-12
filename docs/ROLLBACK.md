# 回滚（版本 / 配置 / 数据库）

> 回滚分三层，**顺序是从外到内：先镜像，再配置，最后才动数据库**。
> 只要没执行数据库降级，前两层都可以在 1 分钟内完成。备份见 [BACKUP_RESTORE.md](BACKUP_RESTORE.md)。

## 0. 先判断要退哪一层

| 症状 | 要回滚的层 | 是否动数据 |
| --- | --- | --- |
| 新版页面白屏 / 接口 500，但数据正常 | 镜像 | 否 |
| 新版启动失败（端口冲突、环境变量缺失） | 配置 | 否 |
| 迁移执行失败或迁移后数据异常 | 数据库 + 镜像 | **是** |
| 只是某个功能不好用，不影响使用 | 不回滚，记录问题 | 否 |

**判断依据**（先看日志，别猜）：

```bash
cd /vol1/docker/freshkeep
docker compose -f docker-compose.yml -f docker-compose.https.yml ps
docker compose logs --tail=80 api | grep -E "ERROR|Traceback|alembic"
docker compose logs --tail=40 web
docker exec freshkeep-db psql -U freshkeep -d freshkeep -tAc "select version_num from alembic_version"
```

## 1. 镜像回滚（最常用，30 秒）

前提：旧镜像还在本机（`docker images` 能看到）。**升级时不要 `docker rmi` 旧镜像**，这就是回滚的燃料。

```bash
# ① 看现有镜像（按创建时间）
docker images | grep freshkeep

# ② 把 latest 指回旧版本
docker tag freshkeep-api:<旧标签> freshkeep-api:latest
docker tag freshkeep-web:<旧标签> freshkeep-web:latest

# ③ 强制重建容器（必须，compose 不会因镜像 ID 变化自动重建）
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate

# ④ 验证
curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1:18443/health
docker compose logs --tail=20 api | grep -E "ERROR|Traceback" || echo "无错误"
```

镜像没有标签、只剩 `latest` 时，用镜像 ID 回退：

```bash
docker images --digests | grep freshkeep        # 找到旧 ID（如 af78090822c9）
docker tag af78090822c9 freshkeep-api:latest
```

> 因此**升级前建议给旧镜像打标签**：`docker tag freshkeep-api:latest freshkeep-api:pre-1.0.0`。

## 2. 配置回滚（改坏了 `.env` / compose）

```bash
cd /vol1/docker/freshkeep
cp .env .env.broken.$(date +%Y%m%d-%H%M%S)    # 留证据
# 用备份的 .env（部署脚本生成的会放 .env.bak；没有就按下表逐项核对）
diff .env .env.bak
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate
```

**配置检查清单**（这四项错了就会起不来）：

| 项 | 检查 |
| --- | --- |
| `POSTGRES_PASSWORD` | 与 pgdata 初始化时一致（不一致会 `password authentication failed`） |
| `FK_HTTP_PORT` / `FK_HTTPS_PORT` | 在 `.env` 里，不是命令行前缀（`sudo` 会重置环境变量） |
| `docker-compose.https.yml` 的 `ports` | 必须是 `ports: !override`，否则 8080 与 18080 同时绑 |
| 证书文件 | `storage/certs/freshkeep.crt` 与 `.key` 都存在且配对 |

## 3. 数据库回滚（最后手段，必须用备份）

⚠ 先做三件事：**停 api**（防写入）、**再备份当前库**（防回滚后才发现还需要现在这份）、**确认备份可读**。

```bash
cd /vol1/docker/freshkeep

# ① 停应用，保留 db
docker compose -f docker-compose.yml -f docker-compose.https.yml stop api web

# ② 给"当前状态"也留一份（回滚也可能后悔）
docker exec freshkeep-db pg_dump -U freshkeep -Fc -f /tmp/before-rollback.dump freshkeep
docker cp freshkeep-db:/tmp/before-rollback.dump backups/before-rollback-$(date +%Y%m%d-%H%M%S).dump

# ③ 从备份恢复（--clean --if-exists 会先删对象再建）
docker exec -i freshkeep-db pg_restore -U freshkeep -d freshkeep --clean --if-exists \
  < backups/freshkeep-<目标时间戳>.dump

# ④ 起服务（entrypoint 会把 schema 迁到当前镜像对应的 head）
docker compose -f docker-compose.yml -f docker-compose.https.yml start api web
docker compose logs --tail=20 api | grep -i alembic
```

**注意**：如果新镜像的迁移比备份里的版本新，`entrypoint` 会自动 `alembic upgrade head`，
即"数据库回到旧数据 + schema 升到新版本"。若这正是你不想要的，就把镜像也一起回退（§1）。

## 4. 迁移回滚（Alembic downgrade）

本项目**不推荐**用 `alembic downgrade` 做生产回滚：迁移只登记版本，DDL 真相在 `database/001_init.sql`，
降级脚本多数是 `DROP TABLE`，会丢数据。**用备份恢复代替。**

只有在"迁移刚执行、还没写入新数据"时才考虑：

```bash
docker exec freshkeep-api alembic current
docker exec freshkeep-api alembic downgrade -1     # 只回一个版本，先确认脚本内容
docker exec freshkeep-api alembic current
```

## 5. 完整回滚演练（建议每季度一次）

```bash
# 在测试目录做，不碰生产
mkdir -p /tmp/rollback-drill && cd /tmp/rollback-drill
git clone https://github.com/0shiyu0/freshkeep.git .
cp .env.example .env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')|" .env
sed -i "s|^HOST_PORT=.*|HOST_PORT=18081|" .env          # 避开生产端口
docker compose up -d --build
curl -s -o /dev/null -w "演练实例 %{http_code}\n" http://127.0.0.1:18081/health
# 记录从零到可用所需时间，这就是真实回滚的最坏耗时
docker compose down
```

## 6. 不可回滚的边界（必须知道）

| 操作 | 能否回滚 | 说明 |
| --- | --- | --- |
| 镜像升级 | ✅ 秒级 | 旧镜像还在即可 |
| `.env` 改动 | ✅ 秒级 | 有 `.env.bak` 即可 |
| 数据库迁移 | ⚠️ 只能靠备份 | `downgrade` 多数会丢表 |
| 已删除的食材/批次 | ❌ | 业务上 `ON DELETE RESTRICT` 保护了主数据，但显式删除不可逆 |
| 已覆盖的备份文件 | ❌ | 备份目录被 `rm` 或被新备份按保留策略删除后无法找回 |
| 已推送的 Git tag | ⚠️ | 可删 tag 重打，但已下载的客户端不会自动更新 |

## 7. 回滚后的收尾

- [ ] 三容器 `healthy`，日志无 `ERROR` / `Traceback`
- [ ] `/health` 与首页 200
- [ ] 登录仍有效（令牌未失效），或重新生成配对码
- [ ] 关键数据抽查：食材数、批次、流水、近期消耗
- [ ] 库存对账差异为 0：`select count(*) from v_batch_reconcile where diff_weight<>0`
- [ ] 在 `docs/CHANGELOG.md` 记录：回滚时间、原因、从哪个版本退到哪个版本、数据是否恢复
