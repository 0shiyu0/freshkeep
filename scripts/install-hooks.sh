#!/bin/sh
# 启用仓库内 Git hooks（团队/多机一致；不使用全局 hooks）
set -eu
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
chmod +x .githooks/* scripts/*.sh 2>/dev/null || true
git config core.hooksPath .githooks
echo "已启用 core.hooksPath = .githooks"
echo "生效的钩子："
ls -1 .githooks | sed 's/^/  /'
echo
echo "验证：git commit 时应看到 pre-commit 的 ✓ 输出"
