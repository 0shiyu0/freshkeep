# docs/state/ · 开发状态留痕

本目录存放**机器生成**的状态记录，用来回答"现在做到哪、上次改了什么、数据库是什么版本"。
不要手工编辑这里的文件（除本 README）。

| 文件 | 谁生成 | 内容 | 是否入库 |
| --- | --- | --- | --- |
| `status.json` | `scripts/status-snapshot.sh` | 分支/HEAD/工作区/迁移版本/表数/测试结果/文档检查 | ✅ 入库（可追溯） |
| `commits.log` | `.githooks/post-commit` | 每次提交一行：时间、hash、标题、文件数、影响域、分支 | ✅ 入库（append-only） |

> `commits.log` 是在提交**之后**写入的，所以它自己会在**下一次**提交里带上。
> 这是刻意的：不在 `post-commit` 里 `--amend`，避免改写历史。

---

## 一条命令生成快照

```bash
./scripts/status-snapshot.sh          # 写文件
./scripts/status-snapshot.sh --print  # 只打印 JSON，不改文件
```

它会把结果同时写进 `docs/PROJECT_STATUS.md` 的自动区块：

```markdown
<!-- AUTO:STATUS:BEGIN -->
…表格…
<!-- AUTO:STATUS:END -->
```

该区块之外的内容由人维护，脚本不会碰。

---

## 自动 vs 手动（说清楚边界）

| 规则 | 触发方式 | 是否真自动 |
| --- | --- | --- |
| 提交前跑测试、查机密、查文档同步、查浮点误用 | `.githooks/pre-commit` | ✅ 是（装了钩子后） |
| 提交后留痕 | `.githooks/post-commit` | ✅ 是 |
| 推送前跑全量测试与文档检查 | `.githooks/pre-push` | ✅ 是 |
| push 时跑 CI（含真 PG 迁移 + 验收用例） | `.github/workflows/ci.yml` | ✅ 是（远端） |
| 迁移前备份、失败给回滚点 | `scripts/migrate-safe.sh` | ⚠️ 半自动（要人执行这一步，而不是 `alembic upgrade`） |
| 会话开始时读文档 + 核对 Git/数据库/测试 | `scripts/session-start.sh` | ⚠️ 半自动（系统无法自动触发"会话开始"，靠 AGENTS.md §12 的规则约束 agent 先跑它） |
| 功能完成后更新 PROJECT_STATUS 正文 | 人 / agent 写 | ❌ 手动（内容判断无法自动化，但脚本会提供原始数据） |

**为什么"每次会话自动执行"只能是半自动**：agent 没有常驻进程，也没有可靠的会话开始事件。
可行的做法是把"检查"做成一条命令 + 一条硬规则（AGENTS.md §12 第 1 条），并在 README/PROJECT_STATUS 顶部反复指向它。
真正 100% 自动的是 **commit / push / CI** 这三个有钩子的环节。

---

## 首次启用

```bash
./scripts/install-hooks.sh     # 设置 core.hooksPath=.githooks
./scripts/session-start.sh     # 看一眼当前状态
```

钩子在本地仓库生效；换机器或重新 clone 后需要再跑一次 `install-hooks.sh`。
