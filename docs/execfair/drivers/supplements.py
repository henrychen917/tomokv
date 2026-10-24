#!/usr/bin/env python3
"""Complete transaction/scatter job coverage through the gate's own interface."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/execfair/correctness'
# One correctness slot on the lane's cores and ports, after the other gate exits.
while not (ROOT / 'build/execfair-followups.exit').exists():
    time.sleep(5)
rows = []
for name, jobs, fused, atomic in (
    ('final-split-batteries', 'debug-0 debug-1 atomic_batteries asan_batteries replyoff bplus script_bounds sort aclfix compat3', 0, 1),
    ('fused-batteries', 'debug-0 debug-1 atomic_batteries asan_batteries replyoff script_bounds sort', 1, 1),
    ('script-bounds-split-a0', 'script_bounds', 0, 0),
    ('script-bounds-fused-a0', 'script_bounds', 1, 0),
):
    explicit = dict(REDIS74_ROOT='/home/user/Projects/redis',
                    GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
                    GATE_ONLY_JOBS=jobs, GATE_TXN_FUSED=str(fused), GATE_TXN_ATOMIC=str(atomic),
                    GATE_LEDGER=str(ROOT / ('build/execfair-' + name + '.tsv')))
    command = ['taskset', '-c', '64-79', 'bash', 'tests/gate.sh', 'full',
               '--server-cores', '64-71', '--load-cores', '72-79', '--load-smt', '',
               '--ports', '30800-30899']
    log = ROOT / ('build/execfair-' + name + '.log')
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **explicit),
                                stdout=stream, stderr=subprocess.STDOUT)
    rows.append(dict(name=name, command=command, environment=explicit,
                     log=str(log.relative_to(ROOT)), exit_code=result.returncode))
    (OUT / 'supplements.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(name, result.returncode, flush=True)
assert all(row['exit_code'] == 0 for row in rows)
