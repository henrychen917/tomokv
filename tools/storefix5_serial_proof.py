#!/usr/bin/env python3
"""Run the quiet-preflight and standard differential jobs serially on lane CPUs."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
receipt = {'waiting_for': ['gate-live-release.log', 'gate-native-release.log'], 'stages': []}
output = DOC / 'serial-proof.json'
def save():
    output.write_text(json.dumps(receipt, indent=2) + '\n')
save()
while receipt['waiting_for']:
    receipt['waiting_for'] = [name for name in receipt['waiting_for']
        if not (DOC / name).exists() or 'GATE(PARTIAL):' not in (DOC / name).read_text()]
    save()
    if receipt['waiting_for']:
        time.sleep(2)
for label, jobs, engine, ports in [
    ('gate-quiet-release', 'zc splitlocal_units', 'uring', '21610-21612'),
    ('gate-differ-uring-serial', 'differ-split differ-armed', 'uring', '21660-21662'),
    ('gate-differ-epoll-serial', 'differ-split differ-armed', 'epoll', '21670-21672'),
]:
    argv = ['tests/gate.sh', 'iteration', '--server-cores', '16-23', '--load-cores', '16-23',
            '--load-smt', '', '--ports', ports, '--shared-correctness-cpus',
            '--candidate-binary', 'build/storefix5/POST']
    env = dict(os.environ, GATE_ONLY_JOBS=jobs, GATE_PROOF_NO_RATES='1',
               GATE_DIFFER_NET_IO=engine, REDIS74_ROOT='/home/user/Projects/redis')
    row = {'log': label + '.log', 'argv': argv, 'jobs': jobs, 'engine': engine, 'started': time.time()}
    receipt['stages'].append(row)
    save()
    with (DOC / row['log']).open('w') as log:
        completed = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    row.update(exit=completed.returncode, finished=time.time())
    save()
receipt['complete'] = True
save()
raise SystemExit(any(row['exit'] for row in receipt['stages']))
