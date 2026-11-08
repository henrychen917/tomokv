#!/usr/bin/env python3
"""Sequential selected correctness jobs; no iteration or performance driver."""
import json
import os
from pathlib import Path
import subprocess
import time

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
# The independently launched original-detector rerun and first production build
# finish before these server-owning jobs take the same lane cores.
while not Path('docs/atomfix6/proof/units-final/exit.json').exists():
    time.sleep(2)
while True:
    p = Path('docs/atomfix6/audit/post-index.json')
    if p.exists() and len(json.loads(p.read_text())) == 14:
        break
    time.sleep(2)
rows = []
for group, engine, fused in [
    ('lane', 'uring', False), ('lane', 'epoll', False),
    ('atomic', 'uring', False), ('atomic', 'uring', True),
    ('features', 'uring', False), ('persistence', 'uring', False),
    ('persistence', 'uring', True), ('placement', 'uring', False),
    ('differ', 'uring', False), ('differ', 'epoll', False),
]:
    argv = ['python3', 'tools/atomfix6_proof.py', group, '--engine', engine]
    if fused: argv += ['--fused']
    result = subprocess.run(argv, env=dict(os.environ, LC_ALL='C'))
    rows.append(dict(group=group, engine=engine, fused=fused, rc=result.returncode))
    Path('docs/atomfix6/proof/suite-index.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(rows[-1], flush=True)
