#!/usr/bin/env python3
"""Bounded PRE/POST attribution for an unchanged full-file Tcl PUBSUB failure."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/climonfix4'
CASE = 'PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments in tests/unit/pubsub.tcl'
results = []
for arm, attempts in [('PRE', 20), ('POST', 5)]:
    binary = ROOT / 'build/climonfix4' / ('tomokv-' + arm)
    manifest = OUT / 'tcl-controls/pubsub-recheck.json'
    for attempt in range(attempts):
        log = ROOT / 'build/climonfix4' / f'pubsub-{arm}-{attempt}.log'
        command = ['taskset', '-c', '16-31', 'bash', 'tests/gate.sh', 'quick',
                   '--server-cores', '16-23', '--load-cores', '24-31',
                   '--server-smt', '', '--load-smt', '', '--ports', '20250-20259',
                   '--candidate-binary', str(binary)]
        env = os.environ | dict(GATE_ONLY_JOBS='redis_tcl', REDIS74_ROOT='/home/user/Projects/redis',
                                GATE_TCL_MANIFEST=str(manifest))
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT)
        run = Path(re.search(r'artifacts: (\S+)', log.read_text())[1])
        row = dict(arm=arm, attempt=attempt, exit=result.returncode, argv=command,
                   binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   artifacts=str(run), env={k: env[k] for k in
                       ('GATE_ONLY_JOBS', 'REDIS74_ROOT', 'GATE_TCL_MANIFEST')}, modes={})
        found = False
        for mode in ('1s', '2s'):
            data = json.loads((run / 'jobs/redis_tcl' / ('redis-tcl-' + mode) /
                               'unit/pubsub/result.json').read_text())
            errors = [e for e in data['events'] if e['status'] == 'err']
            statuses = [e['status'] for e in data['events'] if e.get('test') == CASE]
            assert 'testing' in statuses and any(s in statuses for s in ('ok', 'err'))
            row['modes'][mode] = dict(complete=data['complete'], statuses=statuses, errors=errors)
            found |= 'err' in statuses
        results.append(row)
        (OUT / 'pubsub-recheck-results.json').write_text(json.dumps(results, indent=2) + '\n')
        (OUT / 'jobs' / f'pubsub-{arm.lower()}-{attempt}.json').write_text(
            json.dumps(row, indent=2) + '\n')
        print(arm, attempt, result.returncode, 'named failure' if found else 'named pass', flush=True)
        if arm == 'PRE' and found:
            break
