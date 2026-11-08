#!/bin/sh
# 文档完整性检查：
#   1. 必需文档存在且非空
#   2. 所有 Markdown 相对链接都指向真实文件
#   3. 归档文档不得被当作现行文档引用
set -eu

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

python3 - <<'PY'
import re, sys
from pathlib import Path

root = Path('.')
errors = []

required = [
    'AGENTS.md',
    'docs/PRD.md',
    'docs/ARCHITECTURE.md',
    'docs/DEVELOPMENT_PLAN.md',
    'docs/PROJECT_STATUS.md',
    'docs/CHANGELOG.md',
    'database/001_init.sql',
    'database/002_acceptance_check.sql',
]
for rel in required:
    p = root / rel
    if not p.is_file():
        errors.append(f'缺少必需文件：{rel}')
    elif p.stat().st_size < 200:
        errors.append(f'文件过小（疑似占位）：{rel}')

link_re = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
md_files = [p for p in root.rglob('*.md') if '.git' not in p.parts and 'node_modules' not in p.parts]

for md in md_files:
    text = md.read_text(encoding='utf-8', errors='ignore')
    for raw in link_re.findall(text):
        target = raw.split('#')[0].strip()
        if not target or target.startswith(('http://', 'https://', 'mailto:', '#')):
            continue
        resolved = (md.parent / target).resolve()
        if not resolved.exists():
            errors.append(f'{md}: 链接失效 → {raw}')
        if 'docs/archive/' in str(resolved) and 'archive' not in str(md):
            errors.append(f'{md}: 引用了归档文档（应改指现行文档）→ {raw}')

if errors:
    print('\n'.join(sorted(set(errors))))
    sys.exit(1)
print(f'文档检查通过：{len(required)} 个必需文件齐备，{len(md_files)} 个 Markdown 内链有效')
PY
