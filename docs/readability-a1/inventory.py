#!/usr/bin/env python3
"""Conservative caller inventory at the frozen A1 input; never executes a tool."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = '5c3631281815c1652b3894d1736840c8466a5015'
SUFFIXES = {'.py', '.sh', '.mk', '.cc', '.c', '.h', '.inc'}


def inventory():
    files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, 'tools', 'tests'], cwd=ROOT, text=True).splitlines()
    # Read frozen blobs directly: an ignored scratch checkout is not a report input.
    paths = [p for p in files if Path(p).suffix in SUFFIXES] + ['Makefile']
    objects = subprocess.check_output(
        ['git', 'cat-file', '--batch'], cwd=ROOT,
        input=''.join(f'{BASE}:{path}\n' for path in paths).encode())
    texts, offset = {}, 0
    for path in paths:
        end = objects.index(b'\n', offset)
        _, kind, size = objects[offset:end].split()
        assert kind == b'blob', (path, kind)
        offset = end + 1
        texts[path] = objects[offset:offset + int(size)].decode(errors='replace')
        offset += int(size) + 1
    assert offset == len(objects)
    bybase = {}
    for path in files:
        bybase.setdefault(Path(path).name, []).append(path)
    edges = {}
    for path, text in texts.items():
        imports, patterns = [], []
        if path.endswith('.py'):
            tree = ast.parse(text)
            docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
            literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(n.name + '.py' for n in node.names)
                if isinstance(node, ast.ImportFrom) and node.module: imports.append(node.module + '.py')
                if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) and str(node.values[0].value).startswith(('tests/', 'tools/')):
                    patterns.append(''.join(re.escape(n.value) if isinstance(n, ast.Constant) else '.*' for n in node.values))
            text = '\n'.join(literals)
        else:
            text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith(('# ', '//', '/*', '*')))
        for match in re.finditer(r'(?:tests|tools)/[^\s"\']*\$\{[^}]+\}[^\s"\']*', text):
            patterns.append(re.sub(r'\\\$\\\{.*?\\\}', '.*', re.escape(match[0])))
        edges[path] = sorted({target for name in bybase if name in text or name in imports
                             for target in bybase[name] if target != path} |
                            {target for pattern in patterns for target in files
                             if re.fullmatch(pattern, target)})
    roots = {'Makefile', 'tests/gate.sh', 'tests/gates_test.py', 'tests/gate_ledger_fixture.py',
             'tests/lottery_nightly.sh', 'tools/reorder_sync.py'}
    live = set(roots)
    while True:
        extended = live | {q for p in live for q in edges.get(p, ())}
        if extended == live: break
        live = extended
    callers = {p: sorted(k for k, values in edges.items() if p in values) for p in files}
    return files, texts, edges, live, callers


if __name__ == '__main__':
    files, texts, edges, live, callers = inventory()
    out = ROOT / 'build/readability-a1/inventory.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(files=files, edges=edges, live=sorted(live), callers=callers), indent=2) + '\n')
    print('tracked files:', len(files), 'scripts:', sum(Path(p).suffix in ('.py', '.sh', '.mk') for p in files),
          'reachable:', len(live), 'tools reachable:', sum(p.startswith('tools/') for p in live))
