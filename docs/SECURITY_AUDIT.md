# 安全审计报告（V1.0.0 发布前）

> 审计时间：2026-11-12 · 范围：公开 GitHub 仓库的全部被跟踪文件 + **完整 Git 历史**（46 个提交，2026-11-08 起）
> 结论：**可以公开**。仓库不含任何真实凭据；历史中从未提交过 `.env`、密钥或证书文件。

## 1. 扫描方法

审计在本地仓库执行，命令可复现：

```bash
# 当前被跟踪文件的高危模式
git grep -I -nE "PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|github_pat_|sk-[A-Za-z0-9]{20,}|xox[baprs]-|-----BEGIN"

# 赋值型密码/密钥
git grep -I -nE "(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{6,}['\"]"

# 带密码的连接串
git grep -I -nE "postgres(ql)?(\+psycopg)?://[^:\s]+:[^@\s]{4,}@"

# 历史中曾新增过的敏感文件类型
git log --all --pretty=format: --name-only --diff-filter=A | sort -u \
  | grep -iE '\.(env|key|pem|p12|pfx|crt|dump|sqlite|db|jks|keystore)$'

# 历史中所有 .env* 文件
git log --all --pretty=format: --name-only | sort -u | grep -E '(^|/)\.env'

# 逐提交检查高危关键词
for pat in "PRIVATE KEY" "BEGIN OPENSSH" "AKIA" "ghp_" "POSTGRES_PASSWORD=freshkeep"; do
  echo -n "$pat: "; git rev-list --all | xargs -I{} git grep -I -l "$pat" {} 2>/dev/null | wc -l
done
```

## 2. 扫描结果

| 检查项 | 结果 |
| --- | --- |
| 私钥 / SSH 私钥 / AWS Key / GitHub Token / OpenAI Key / Slack Token | **0 命中** |
| 赋值型密码与密钥（排除示例值） | **0 命中** |
| 带真实密码的 PostgreSQL 连接串 | **0 命中**（`ci.yml` 里的 `postgres:postgres` 是 CI 临时服务账号，非生产凭据） |
| 历史中新增过的敏感文件类型（`.env`/`.key`/`.pem`/`.crt`/`.dump`/`.db`/`.keystore`） | **0 个** |
| 历史中出现过的 `.env*` 文件 | 仅 `.env.example`（占位值） |
| 历史提交中的高危关键词 | 全部 **0 个 commit** |

**因此不存在"曾经提交过密钥、需要更换密钥"的情况**，也无需重写 Git 历史。

> 说明：审计期间使用的 NAS 登录凭据从未写入任何文件——只在会话内存与 `/tmp` 临时文件中存在，
> 使用后即删除，且 `git grep` 在全部 46 个提交中检索该字符串为 0 命中。

## 3. `.gitignore` 覆盖

| 类别 | 规则 | 状态 |
| --- | --- | --- |
| 数据库数据目录 | `pgdata/`、`data/`、`*.db*` | ✅ |
| 上传 / 导出 / 日志 | `storage/uploads/*`、`storage/exports/*`、`storage/logs/*` | ✅（保留 `.gitkeep`） |
| 证书与私钥 | `storage/certs/`、`*.pem`、`*.key`、`*.crt`、`*.p12`、`*.pfx`、`*.keystore`、`*.jks` | ✅ |
| 环境文件 | `.env`、`.env.*`、`!.env.example` | ✅ |
| 备份与导出产物 | `backups/*`、`*.dump`、`*.sql.gz`、`*.tar.gz` | ✅ |
| 依赖与构建产物 | `node_modules/`、`.venv/`、`__pycache__/`、`frontend/dist/`、`frontend/.vite/` | ✅ |
| 测试缓存 | `.pytest_cache/`、`.ruff_cache/`、`.pytest-backups/`、`coverage/`、`htmlcov/` | ✅ |
| 系统与编辑器 | `.DS_Store`、`Thumbs.db`、`.idea/`、`.vscode/` | ✅ |
| 例外（必须入库） | `!docs/state/commits.log`、`!storage/**/.gitkeep`、`!backups/.gitkeep` | ✅ |

验证：

```bash
git check-ignore -v pgdata storage/uploads/x storage/certs/freshkeep.key backups/v1.0.0-pre/x.dump .env
# 五条全部命中规则，无输出表示未被忽略（视为缺陷）
```

## 4. `.dockerignore` 覆盖

构建上下文有两个：后端用**仓库根**，前端用 `frontend/`。

| 类别 | 已排除 | 说明 |
| --- | --- | --- |
| 版本控制与元数据 | `.git`、`.github`、`.gitignore`、`.gitattributes`、`.editorconfig` | 不必要进上下文 |
| 依赖与缓存 | `node_modules`、`**/node_modules`、`backend/.venv`、`.venv`、`**/__pycache__`、`.pytest_cache`、`frontend/.vite` | 本机 `node_modules` 310MB |
| 运行时数据 | `pgdata`、`data`、`storage`、`backups`、`*.dump`、`*.tar.gz` | **含证书私钥与数据库 dump，必须排除** |
| 密钥 | `.env`、`.env.*`、`*.pem`、`*.key`、`*.crt` | 避免进入构建缓存 |
| 原生工程 | `frontend/android`（24M）、`frontend/ios` | 不参与 Web 镜像 |
| 文档与归档 | `docs`、`legacy`、`*.md`（保留 `README.md`） | 减小上下文 |

`database/` 与 `backend/`、`frontend/` **未排除**（镜像构建必需）。

## 5. 第三方依赖许可证

### Python（`backend/requirements.txt`，直接依赖）

| 包 | 许可证 |
| --- | --- |
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| sqlalchemy | MIT |
| alembic | MIT |
| **psycopg** | **LGPL-3.0-only** |
| pydantic | MIT |
| pypinyin | MIT |
| apscheduler | MIT |
| python-multipart | Apache-2.0 |
| argon2-cffi | MIT |
| pytest | MIT |
| httpx | BSD-3-Clause |

### npm（`frontend/package.json` 生产依赖）

| 许可证 | 数量 | 代表包 |
| --- | --- | --- |
| MIT | 16 | `@capacitor/*`、`vue`、`pinia`、`axios`、`vue-router` |
| Apache-2.0 | 1 | `echarts` |

### 合规判定

- 项目自身以 **MIT** 发布，与上述 MIT / BSD / Apache-2.0 依赖兼容。
- **`psycopg` 是 LGPL-3.0**：本项目以**未修改的库形式动态使用**（`import psycopg`），
  未静态链接、未修改源码、未衍生作品，符合 LGPL 的「动态链接使用」豁免。
  分发容器镜像时已通过 `pip install` 安装二进制 wheel，用户可自行替换该库版本。
- **无 GPL / AGPL / SSPL 等强 copyleft 依赖**，不会传染项目自身的 MIT 许可。

## 6. 发现的问题与处置

| # | 问题 | 风险 | 处置 |
| --- | --- | --- | --- |
| 1 | 根目录存在 9 个旧静态站文件（`index.html`、`js/`、`css/`、`icons/`、`sw.js`、`manifest.webmanifest`、`tests/selftest.html`） | 公开仓库结构混乱，读者误以为有两套前端 | 已 `git mv` 到 `legacy/`，并加 `legacy/README.md` 说明「不参与构建」 |
| 2 | `.dockerignore` 未排除 `storage/`（含**证书私钥**）、`backups/`（含数据库 dump）、`android/`、`ios/` | 私钥与用户数据进入构建上下文/缓存 | 已补齐（见 §4） |
| 3 | `.gitignore` 缺 `*.dump`、`*.tar.gz`、`*.key`、`*.crt`、`.idea/`、`.vscode/`、`frontend/.vite`、`coverage/` | 误提交备份或密钥的可能性 | 已补齐（见 §3） |
| 4 | `ci.yml` 表数断言写死 `25`（实际 28，含 `alembic_version`），且引用旧表结构口径 | CI 必红，掩盖真实失败 | 已改为 28，并新增「视图数=2」「迁移版本=0004」两项断言 |
| 5 | `README.md` 主体仍是旧静态版说明（"双击 index.html""部署到 GitHub Pages""数据存 localStorage"） | 公开仓库首页与实现严重不符 | 已整篇重写为当前架构（Vue + FastAPI + PostgreSQL + Compose） |
| 6 | NAS 部署目录残留约 200MB 上传产物（`fk_images*.tar.gz` 等） | 占用空间；旧镜像包可能含旧代码 | 待清理（阶段 2 执行） |

## 7. 仍在使用的安全边界（运行时，不属于仓库内容）

| 项 | 现状 |
| --- | --- |
| 网段白名单 | `ALLOW_CIDR` 默认仅局域网与组网网段（`192.168/16` 等） |
| 端口暴露 | 仅 `web` 暴露 18080/18443；`api`(8000)、`db`(5432) 不映射到宿主机 |
| 传输加密 | HTTPS 版本启用 TLSv1.2/1.3 + HSTS + CSP + X-Frame-Options + nosniff |
| 证书 | 自签（SAN 含内网 IP），**仅内网使用**；公网需换 CA 证书 |
| 凭据存放 | `.env`（600，NAS 本地随机生成的 `POSTGRES_PASSWORD`），不入库、不上传 |
| SSH | 目前为密码登录；建议改为密钥登录并限制来源（未在本阶段执行） |

## 8. 复现审计

```bash
./scripts/check-docs.sh          # 文档完整性 + 内链
git grep -I -nE "sk-|ghp_|AKIA|PRIVATE KEY" -- . || echo "clean"
git log --all --pretty=format: --name-only --diff-filter=A | sort -u | grep -iE '\.(env|key|pem)$' || echo "no secrets in history"
```

结论：**不存在需要提交的敏感信息；数据库与上传文件不会进入 Git；公开仓库不含真实运行配置。**
