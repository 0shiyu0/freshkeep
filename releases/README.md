# 发布产物（v1.0.0）

> 本目录只保存**发布说明**；镜像包本身（`*.tar.gz`，约 94MB）在 `.gitignore` 内，不随仓库分发。
> 部署步骤见 [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)，回滚见 [../docs/ROLLBACK.md](../docs/ROLLBACK.md)。

## 1. 版本信息

| 项 | 值 |
| --- | --- |
| 版本 | **v1.0.0** |
| 构建时间 | 2026-11-12 |
| 目标平台 | `linux/amd64`（x86_64 NAS / 服务器） |
| 源码 | 本仓库 `main` 分支对应 tag `v1.0.0` |

## 2. 镜像指纹

| 镜像 | ID（sha256 前 12 位） | 大小 | 架构 |
| --- | --- | --- | --- |
| `freshkeep-api:1.0.0` | `683a79575c17` | 77.6 MB | linux/amd64 |
| `freshkeep-web:1.0.0` | `3e74d5ade098` | 21.4 MB | linux/amd64 |
| `postgres:16-alpine`（基础依赖，不从本仓库分发） | 由官方镜像提供 | — | — |

镜像构建路径：

```bash
docker buildx build --platform linux/amd64 --load \
  -t freshkeep-api:1.0.0 -f backend/Dockerfile .
docker buildx build --platform linux/amd64 --load \
  -t freshkeep-web:1.0.0 -f frontend/Dockerfile ./frontend
```

## 3. 镜像包

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| `freshkeep-1.0.0-amd64.tar.gz` | 94 MB | `982ae6a4cc55538aaadd390fee826cf13a785a6b0ff37b132a138b3b9eae134a` |

校验与载入：

```bash
# 校验完整性（在 NAS / 目标机上执行）
shasum -a 256 freshkeep-1.0.0-amd64.tar.gz
# 期望：982ae6a4cc55538aaadd390fee826cf13a785a6b0ff37b132a138b3b9eae134a

docker load -i freshkeep-1.0.0-amd64.tar.gz
docker tag freshkeep-api:1.0.0 freshkeep-api:latest
docker tag freshkeep-web:1.0.0 freshkeep-web:latest
```

启动（**必须带 `--force-recreate`**，否则 compose 不会因为镜像 ID 变化而重建容器）：

```bash
cd /vol1/docker/freshkeep
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate
```

## 4. 发布前已通过的验证

| 检查 | 结果 |
| --- | --- |
| api 镜像依赖完整 | `fastapi 0.162.2` / `sqlalchemy 2.1.8` / `psycopg 3.3.8` 均可导入 |
| api 镜像代码可加载 | `import app.main` 成功，OpenAPI **85 条路径** |
| web 镜像产物完整 | `index.html`、`manifest.webmanifest`、`offline.html`、`icons/`、**45 个 assets** |
| web 静态资源可服务 | `/`、`/sw.js`、`/manifest.webmanifest`、`/offline.html`、`/icons/icon-192.png` 均 **200** |
| 镜像包可载入 | `docker load` 成功载入 **2 个镜像** |
| 后端测试 | `pytest` 232 passed，覆盖率 87.08%（门槛 80%） |
| 代码质量 | `ruff check app tests` 全过；`prettier --check` 全过 |

## 5. 已知属性（不是缺陷，但需知道）

1. **web 镜像不能脱离 api 单独运行**：nginx 在**启动时**解析 upstream `api` 主机名
   （`/etc/nginx/conf.d/default.conf:23`），容器单独 `docker run` 会因 `host not found in upstream "api"`
   直接退出（exit 1）。用 compose 时 `depends_on: api(healthy)` 已保证顺序，正常部署不受影响。
   若要在容器外验证静态资源，可临时加 `--add-host api:127.0.0.1`。
2. **镜像不含数据**：`pgdata` / `storage` / `backups` 都是 bind mount，镜像本身无任何用户数据。
3. **`ENABLE_SCHEDULER` 由 compose 传入**（`true`）。单独 `docker run` 时不设该变量则定时任务不启动。

## 6. 自动发布：GitHub Actions（推荐）

推 tag 会触发 `.github/workflows/release.yml`：在 ubuntu runner 上重新构建 linux/amd64 镜像 →
推送 GHCR → 创建 GitHub Release → 附上 `freshkeep-<tag>-amd64.tar.gz` 与 `.sha256`。
Actions 自带 `GITHUB_TOKEN`，**不需要本地任何凭据**。

```bash
git tag -a v1.0.0 -m "v1.0.0"      # 已存在则跳过
git push origin v1.0.0              # 触发 workflow
# 进度：仓库 Actions 页面，或
curl -s https://api.github.com/repos/0shiyu0/freshkeep/actions/runs?per_page=3 | grep -E '"name"|"status"|"conclusion"'
```

前置条件：仓库 **Settings → Actions → General → Workflow permissions** 需为
**Read and write permissions**（否则创建 Release 与推 GHCR 会 403）。

## 7. 手动推送 GHCR（备选，需要 PAT）

若不用 Actions，可在本地执行（需要一个带 `write:packages` 权限的 PAT）：

具备一个具有 `write:packages` 权限的 PAT 后，执行：

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u 0shiyu0 --password-stdin
docker tag freshkeep-api:1.0.0 ghcr.io/0shiyu0/freshkeep-api:1.0.0
docker tag freshkeep-api:1.0.0 ghcr.io/0shiyu0/freshkeep-api:latest
docker tag freshkeep-web:1.0.0 ghcr.io/0shiyu0/freshkeep-web:1.0.0
docker tag freshkeep-web:1.0.0 ghcr.io/0shiyu0/freshkeep-web:latest
docker push ghcr.io/0shiyu0/freshkeep-api:1.0.0
docker push ghcr.io/0shiyu0/freshkeep-api:latest
docker push ghcr.io/0shiyu0/freshkeep-web:1.0.0
docker push ghcr.io/0shiyu0/freshkeep-web:latest
```

推送后把 `docker-compose.yml` 的 `build:` 换成 `image: ghcr.io/0shiyu0/freshkeep-api:1.0.0`
即可让 NAS 直接从 registry 拉取固定版本（这是阶段 7「NAS 固定版本部署」的入口）。
