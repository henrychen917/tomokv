#!/usr/bin/env python3
"""Audit every listed file against PRE with A1's raw preprocessing-token lexer."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from measure_style import BASE, GENERATED, ROOT, original
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
from format import anchors, file_list, literals


def digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


rows = []
for filename in file_list():
    before, after = original(filename), (ROOT / filename).read_bytes().decode()
    pre_tokens = tuple(t.text for t in cpp.lex(before))
    post_tokens = tuple(t.text for t in cpp.lex(after))
    pre_literals, post_literals = literals(before), literals(after)
    rows.append(dict(path=filename, changed=before != after,
                     tokens=len(pre_tokens), literals=len(pre_literals),
                     tokens_equal=pre_tokens == post_tokens,
                     literals_equal=pre_literals == post_literals,
                     anchors_equal=anchors(before) == anchors(after),
                     token_sha256=digest(post_tokens), literal_sha256=digest(post_literals),
                     raw_literals=sum(m.lastgroup == 'raw' for m in cpp.LEXER.finditer(before))))
excluded = sorted(GENERATED)
excluded.extend(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE,
                                        'third_party', 'src/third_party', 'tools/archive'],
                                       cwd=ROOT, text=True).splitlines())
changed_exclusions = [p for p in excluded if subprocess.check_output(
    ['git', 'show', f'{BASE}:{p}'], cwd=ROOT) != (ROOT / p).read_bytes()]
exceptions = [r for r in rows if not all(r[k] for k in ('tokens_equal', 'literals_equal', 'anchors_equal'))]
result = dict(base=BASE, files=len(rows), changed_files=sum(r['changed'] for r in rows),
              tokens=sum(r['tokens'] for r in rows), literals=sum(r['literals'] for r in rows),
              raw_literals=sum(r['raw_literals'] for r in rows),
              excluded_files=len(excluded), changed_exclusions=changed_exclusions,
              exceptions=exceptions, rows=rows)
out = ROOT / 'build/readability-a2/source-proof.json'
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
raise SystemExit(bool(exceptions or changed_exclusions))
