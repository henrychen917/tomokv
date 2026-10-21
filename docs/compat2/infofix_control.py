#!/usr/bin/env python3
"""Check the epoll INFO byte-counter failure against frozen PRE at the matrix geometry."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from compat2_support import server

OUT = ROOT / 'docs/compat2/infofix-control'
OUT.mkdir(exist_ok=False)
results = []
for arm, binary in [('pre', ROOT / 'build/compat2/pre-source/build/tomokv'),
                    ('post', ROOT / 'build/tomokv')]:
    for mode in ('1s', '2s'):
        for engine in ('epoll', 'uring'):
            for atomic in (0, 1):
                name = f'{arm}-{mode}-{engine}-a{atomic}'
                # Match the standard matrix's balancing/default runtime and armed fused lane.
                extra = ['--atomic', str(atomic), '--key-lb', '1', '--client-lb', '1',
                         '--read-local', '1' if mode == '1s' else '0']
                with server(binary, OUT / (name + '-target'), 26870, '64-71', mode, engine, extra), \
                     server('/home/user/Projects/redis74/src/redis-server', OUT / (name + '-oracle'),
                            26871, '72', oracle=True):
                    argv = ['taskset', '-c', '73-79', 'python3', 'tests/differ.py',
                            '127.0.0.1', '26870', '127.0.0.1', '26871', 'infofix', '7']
                    with (OUT / (name + '.log')).open('w') as log:
                        rc = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, 'GATE_DIFFER_COVERAGE': str(OUT / (name + '.coverage.json'))}).returncode
                results.append(dict(name=name, argv=argv, returncode=rc))
                (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
                print(name, rc, flush=True)
