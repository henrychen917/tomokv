#!/usr/bin/env python3
"""Count comment groups at unchanged preprocessing-token boundaries."""
from bisect import bisect_right
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
BASE = '7595a6705ac19c1a4eecf7798fde594332f0be0c'

def groups(text):
    ends = [token.end for token in cpp.lex(text)]
    result = {}
    for match in cpp.LEXER.finditer(text):
        if match.lastgroup == 'comment' and 'TOMO_TOOL_' not in match[0]:
            boundary = bisect_right(ends, match.start())
            result.setdefault(boundary, []).append(match[0])
    return {key: re.sub(r'\s+', ' ', ' '.join(value)) for key, value in result.items()}

files = subprocess.check_output(['git', 'diff', BASE, '--name-only', '--', 'src/'],
                                cwd=ROOT, text=True).splitlines()
rows = []
for name in files:
    before = subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=ROOT).decode()
    after = (ROOT / name).read_text()
    old, new = groups(before), groups(after)
    assert tuple(t.text for t in cpp.lex(before)) == tuple(t.text for t in cpp.lex(after)), name
    rows.append({'file': name,
                 'rewritten_or_retired_groups': sum(new.get(k) != value for k, value in old.items()),
                 'new_groups': sum(k not in old for k in new),
                 'phase_landmarks': len(re.findall(r'// Phase [0-9]+:', after)),
                 'file_header': after.startswith('//')})
result = {'definition': 'Non-tool comments grouped by preceding preprocessing-token boundary; '
                       'whitespace normalized. Rewrites include a former group relocated or '
                       'retired into the decision log. Added contracts can expand an existing group.',
          'files': rows,
          'totals': {key: sum(row[key] for row in rows) for key in
                     ('rewritten_or_retired_groups', 'new_groups', 'phase_landmarks', 'file_header')}}
(ROOT / 'docs/readability-a9/evidence/comment-counts.json').write_text(
    json.dumps(result, indent=2) + '\n')
print(json.dumps(result['totals']))
