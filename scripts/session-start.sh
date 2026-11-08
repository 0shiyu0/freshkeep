#!/bin/sh
# =============================================================================
# 会话启动检查：把「必须先了解的状态」一次性摆出来，避免凭对话历史猜进度。
#
#   ./scripts/session-start.sh
#
# 只读，不修改任何文件。
# =============================================================================
set -u

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo .)
cd "$ROOT"

# 让非登录 shell 也能找到 Homebrew 装的 PostgreSQL（zsh 的 ~/.zshrc 不会在这些脚本里生效）
for _p in /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@16/bin; do
  if [ -d "$_p" ]; then case ":$PATH:" in *":$_p:"*) ;; *) PATH="$_p:$PATH" ;; esac; fi
done
export PATH

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m! %s\033[0m\n' "$1"; }
good() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

bold "0. 必读文档"
for f in AGENTS.md docs/PRD.md docs/ARCHITECTURE.md docs/DEVELOPMENT_PLAN.md docs/PROJECT_STATUS.md docs/CHANGELOG.md; do
  if [ -f "$f" ]; then
    printf '  %-34s %5s 行\n' "$f" "$(wc -l < "$f" | tr -d ' ')"
  else
    warn "缺失：$f"
  fi
done

bold "1. Git 工作区"
printf '  分支：%s   HEAD：%s\n' "$(git rev-parse --abbrev-ref HEAD)" "$(git rev-parse --short HEAD)"
if [ -z "$(git status --porcelain)" ]; then
  good "工作区干净"
else
  warn "有未提交改动："
  git status --porcelain | sed 's/^/    /' | head -10
fi
printf '  未推送提交：%s\n' "$(git rev-list --count @{u}..HEAD 2>/dev/null || echo '?')"
echo "  最近 5 次提交："
git log -5 --pretty='    %h %ad %s' --date=short

bold "2. 数据库"
if command -v psql >/dev/null 2>&1; then
  VER=$(psql -d freshkeep -tAc "select version_num from alembic_version" 2>/dev/null || true)
  N=$(psql -d freshkeep -tAc "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name <> 'alembic_version'" 2>/dev/null || echo "?")
  if [ -n "$VER" ]; then good "迁移版本 ${VER}，$N 张表"; else
    warn "连不上库或 alembic_version 为空（跑 ./scripts/db-init.sh）"; fi
else
  warn "psql 不在 PATH：export PATH=\"/opt/homebrew/opt/postgresql@16/bin:\$PATH\""
fi

bold "3. 测试与构建"
if [ -x backend/.venv/bin/python ]; then
  OUT=$(cd backend && .venv/bin/python -m pytest 2>&1 | grep -E '[0-9]+ (passed|failed)' | tail -1)
  case "$OUT" in
    *failed*) warn "后端测试失败：$OUT" ;;
    "") warn "后端测试无结果（可能收集失败）" ;;
    *) good "后端测试：$OUT" ;;
  esac
else
  warn "backend/.venv 不存在 → ./scripts/dev-setup.sh"
fi
[ -d frontend/dist ] && good "前端产物 dist/ 存在" || warn "前端未构建 → cd frontend && npm run build"

bold "4. 文档一致性"
./scripts/check-docs.sh 2>&1 | tail -5

bold "5. 下一步"
python3 - <<'PY' 2>/dev/null || echo "  （读 docs/DEVELOPMENT_PLAN.md 的「总览」表确认未完成项）"
import re
from pathlib import Path
t = Path('docs/DEVELOPMENT_PLAN.md').read_text(encoding='utf-8')
rows = [l for l in t.splitlines() if l.startswith('|') and ('⬜' in l or '🔄' in l)]
for r in rows[:4]:
    cells = [c.strip() for c in r.strip('|').split('|')]
    print('  ' + ' / '.join(cells[:3]))
PY
echo
echo "以上状态以文件与数据库为准确认后，再继续开发。规则见 AGENTS.md §12。"
