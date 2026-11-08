#!/bin/sh
# =============================================================================
# 状态快照：采集 Git / 数据库 / 测试 / 构建的真实状态，写入
#   docs/state/status.json
#   docs/PROJECT_STATUS.md 的自动区块（<!-- AUTO:STATUS:BEGIN --> … END）
#
#   ./scripts/status-snapshot.sh          采集并写入
#   ./scripts/status-snapshot.sh --print  只打印，不写文件
# =============================================================================
set -eu

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

# 让非登录 shell 也能找到 Homebrew 装的 PostgreSQL（zsh 的 ~/.zshrc 不会在这些脚本里生效）
for _p in /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@16/bin; do
  if [ -d "$_p" ]; then case ":$PATH:" in *":$_p:"*) ;; *) PATH="$_p:$PATH" ;; esac; fi
done
export PATH


MODE=${1:-write}

BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD=$(git rev-parse --short HEAD)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)
RECENT=$(git log -5 --pretty='%h %ad %s' --date=short | tr '\n' '|' | sed 's/|$//')

MIG="n/a"; TABLES="n/a"; DB_OK="false"
if command -v psql >/dev/null 2>&1; then
  if MIG_RAW=$(psql -d freshkeep -tAc "select version_num from alembic_version" 2>/dev/null); then
    DB_OK="true"; MIG=${MIG_RAW:-none}
    # 只统计业务表，排除 alembic_version（否则与文档里的 25 张对不上）
    TABLES=$(psql -d freshkeep -tAc "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name <> 'alembic_version'" 2>/dev/null || echo "?")
  fi
fi

TESTS="未运行"
if [ -x backend/.venv/bin/python ]; then
  OUT=$(cd backend && .venv/bin/python -m pytest 2>&1 | grep -E '[0-9]+ (passed|failed)' | tail -1 || true)
  [ -n "$OUT" ] && TESTS=$OUT
fi

BUILD="不存在"
[ -d frontend/dist ] && BUILD="已构建"

DOCS_OK="false"; ./scripts/check-docs.sh >/dev/null 2>&1 && DOCS_OK="true"

NOW=$(date '+%Y-%m-%d %H:%M')

export BRANCH HEAD DIRTY UNTRACKED AHEAD RECENT MIG TABLES DB_OK TESTS BUILD DOCS_OK NOW MODE

python3 - <<'PY'
import json, os, re
from pathlib import Path

v = {k: os.environ[k] for k in
     ('BRANCH','HEAD','DIRTY','UNTRACKED','AHEAD','RECENT','MIG','TABLES','DB_OK','TESTS','BUILD','DOCS_OK','NOW')}
v['DIRTY'] = int(v['DIRTY']); v['UNTRACKED'] = int(v['UNTRACKED']); v['AHEAD'] = int(v['AHEAD'])
v['DB_OK'] = v['DB_OK'] == 'true'; v['DOCS_OK'] = v['DOCS_OK'] == 'true'
v['RECENT'] = [r for r in v['RECENT'].split('|') if r]

if os.environ['MODE'] == '--print':
    print(json.dumps(v, ensure_ascii=False, indent=2))
    raise SystemExit(0)

Path('docs/state').mkdir(parents=True, exist_ok=True)
Path('docs/state/status.json').write_text(
    json.dumps(v, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

block = f"""<!-- AUTO:STATUS:BEGIN -->
> 本区块由 `scripts/status-snapshot.sh` 于 {v['NOW']} 自动生成，**不要手改**。

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `{v['BRANCH']}` / `{v['HEAD']}` |
| 工作区 | {'干净' if v['DIRTY'] == 0 else f"{v['DIRTY']} 个未提交改动"}，未跟踪 {v['UNTRACKED']} 个 |
| 未推送提交 | {v['AHEAD']} |
| 数据库 | {'可连' if v['DB_OK'] else '不可连'}，迁移版本 `{v['MIG']}`，{v['TABLES']} 张表 |
| 后端测试 | {v['TESTS']} |
| 前端产物 | {v['BUILD']} |
| 文档检查 | {'通过' if v['DOCS_OK'] else '有失效链接'} |

最近 5 次提交：

```
{chr(10).join(v['RECENT'])}
```
<!-- AUTO:STATUS:END -->"""

p = Path('docs/PROJECT_STATUS.md')
text = p.read_text(encoding='utf-8')
if '<!-- AUTO:STATUS:BEGIN -->' in text:
    text = re.sub(r'<!-- AUTO:STATUS:BEGIN -->.*?<!-- AUTO:STATUS:END -->', block, text, flags=re.S)
else:
    text = text.rstrip() + '\n\n---\n\n## 自动状态快照\n\n' + block + '\n'
p.write_text(text, encoding='utf-8')
print(f'已更新 docs/state/status.json 与 docs/PROJECT_STATUS.md 自动区块（{v["NOW"]}）')
PY
