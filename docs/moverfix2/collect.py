#!/usr/bin/env python3
"""Retain the gate's own complete job receipts and count all required legs."""
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/moverfix2'
log = (OUT / 'gate.log').read_text()
run = Path(re.search(r'artifacts: (\S+)', log)[1])
assert 'GATE(PARTIAL): 10 ok, 0 FAIL' in log
# Preserve authoritative ledgers, completion markers, server shutdown logs, all
# mover legs, and the complete identity JSON. Large binaries/disassemblies stay
# in the original build run; their paths/digests are in the inventory below.
kept = []
for path in sorted(run.rglob('*')):
    if not path.is_file():
        continue
    rel = path.relative_to(run)
    if path.suffix in ('.objdump', '.pre', '.post') or path.name == 'fifo-twin':
        continue
    if path.suffix == '.diff' and '\n--- ' not in path.read_text():
        continue
    target = OUT / 'gate' / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    kept.append(dict(path=str(target.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

rows = []
families = ('RPOPLPUSH', 'LMOVE', 'BRPOPLPUSH', 'BLMOVE', 'LMPOP', 'ZMPOP', 'SMOVE')
for mode, engine, databases in itertools.product(('1s', '2s'), ('uring', 'epoll'), (1, 16)):
    legs = []
    for kind, family in [('unit', f) for f in families] + [('live', f) for f in (*families, 'T05', 'G5')]:
        path = run / 'jobs/moverfix' / f'{kind}-{mode}-{engine}-{databases}-{family}.log'
        text = path.read_text()
        assert text.strip(), path
        assert 'Traceback' not in text and 'FAIL' not in text, path
        hits = len(re.findall(r'^HIT ', text, re.M))
        if kind == 'unit':
            assert hits == 8 and 'PASS moverfix deterministic claims' in text, path
        legs.append(dict(name=path.name, bytes=path.stat().st_size, hits=hits,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    rows.append(dict(mode=mode, engine=engine, databases=databases, legs=legs))
assert sum(len(row['legs']) for row in rows) == 128
assert sum(leg['hits'] for row in rows for leg in row['legs']) == 448
(OUT / 'leg-inventory.json').write_text(json.dumps(rows, indent=2) + '\n')

receipt = json.loads((run / 'jobs/reorder_identity/receipt/identity/audit.json').read_text())
assert receipt['expected_bodies'] == {'tomo': 145, 'tomo_db0': 146}
assert len(receipt['rows']) == 291 and all(row['equal'] for row in receipt['rows'])
negative = 'PASS missing policy symbol, missing split-local parser and changed opcode fail strict identity'
assert negative in (run / 'jobs/reorder_identity/receipt.log').read_text()
unchanged = {}
for rel in ('tests/reorder_noop.py', 'tests/reorder_receipt.py', 'tests/gates_test.py', 'tests/gate.sh'):
    old = subprocess.check_output(['git', 'show', 'c100f703f:' + rel], cwd=ROOT)
    new = (ROOT / rel).read_bytes()
    assert old == new, rel
    unchanged[rel] = hashlib.sha256(new).hexdigest()
report = dict(run_directory=str(run), pass_rows=10, fail_rows=0, mover_rows=8,
              legs=128, deterministic_hits=448, r7_bodies=291,
              binary_sha256=receipt['post_sha256'], negative_controls_pass=True,
              unchanged_guard_sources=unchanged, preserved=kept)
(OUT / 'receipt-inventory.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS 10 rows, 128 mover legs, 448 deterministic hits, 291 R7 bodies, all three controls')
