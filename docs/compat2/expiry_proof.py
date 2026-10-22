#!/usr/bin/env python3
"""Final C2 row and candidate-injection controls with isolated positive event classes."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/compat2/expiry-complete'
OUT.mkdir(exist_ok=False)
arms = [('pre', 'build/compat2/pre-source/build/tomokv', False),
        ('post', 'build/tomokv', False), ('pad', 'build/compat2/tomokv-pad-a', False),
        ('mset-pre', 'build/compat2/mset-pre-v2/tomokv', True),
        ('mset-post', 'build/compat2/mset-post-complete/tomokv', True)]
results = []
for mode in ('1s', '2s'):
    for engine in ('epoll', 'uring'):
        for arm, binary, injected in arms:
            name = f'{arm}-{mode}-{engine}'
            argv = ['taskset', '-c', '73-79', 'python3', 'tests/expire_notify.py',
                    '--binary', binary, '--output', str(OUT / name), '--mode', mode,
                    '--engine', engine, '--cores', '64-71', '--port', '26840']
            if injected:
                argv.append('--synthetic-mset')
            with (OUT / (name + '.log')).open('w') as log:
                rc = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
            expected = 0 if arm in ('post', 'mset-post') else 1
            results.append(dict(name=name, argv=argv, returncode=rc, expected=expected))
            (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
            print(name, rc, flush=True)
            assert rc == expected, (name, rc, expected)
