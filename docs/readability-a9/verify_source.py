#!/usr/bin/env python3
"""Record the lane's source/literal/marker identity against both reviewed revisions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
from format import anchors, literals

BASE = '7595a6705ac19c1a4eecf7798fde594332f0be0c'
PRE = '5c3631281815c1652b3894d1736840c8466a5015'
files = subprocess.check_output(
    ['git', 'diff', BASE, '--name-only', '--', 'src/'], cwd=ROOT, text=True).splitlines()
result = {'base': BASE, 'frozen_pre': PRE, 'renames': [], 'files': []}
for name in files:
    after = (ROOT / name).read_bytes().decode()
    row = {'file': name}
    for label, revision in [('base', BASE), ('pre', PRE)]:
        before = subprocess.check_output(['git', 'show', f'{revision}:{name}'], cwd=ROOT).decode()
        original = tuple(token.text for token in cpp.lex(before))
        current = tuple(token.text for token in cpp.lex(after))
        row[label] = {
            'tokens_identical': original == current,
            'literals_identical': literals(before) == literals(after),
            'tokens': len(current),
            'token_sha256': hashlib.sha256(json.dumps(current).encode()).hexdigest(),
        }
        if label == 'base':
            row[label]['tool_markers_identical'] = anchors(before) == anchors(after)
            assert row[label]['tool_markers_identical'], row
        assert row[label]['tokens_identical'] and row[label]['literals_identical'], row
    result['files'].append(row)
output = ROOT / 'docs/readability-a9/evidence/source-identity.json'
output.write_text(json.dumps(result, indent=2) + '\n')
print(f'{len(files)} files: exact preprocessing tokens and literal bytes match lane base and '
      'frozen PRE; tool-marker boundaries match lane base (A1 postdates PRE); no renames')
