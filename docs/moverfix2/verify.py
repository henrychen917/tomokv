#!/usr/bin/env python3
"""Authorized correctness jobs only; no full gate or performance work."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/moverfix2'
assert set(os.sched_getaffinity(0)) <= set(range(80, 96))
ENV = dict(os.environ, GATE_TEST_PORT='23879',
           PYTHONPATH=str(ROOT / 'docs/moverfix/port-scope'))
rows = []


def run(name, argv, env=ENV):
    print('START', name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    rows.append(dict(name=name, argv=argv, rc=result.returncode))
    (OUT / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('DONE', name, result.returncode, flush=True)
    return result.returncode


gate = (ROOT / 'tests/gate.sh').read_text()
body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
command = body.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
targets = shlex.split(command.replace('\\\n', ' '))
assert targets and all(target.startswith('build/') for target in targets)
assert run('build', ['taskset', '-c', '80-95', 'make', '-j16', 'all',
                     *targets, 'mdbqsbr-live-arms']) == 0, 'build failed'
freshness = []
for target in ['all', *targets]:
    result = subprocess.run(['make', '-q', target], cwd=ROOT)
    freshness.append(dict(target=target, rc=result.returncode))
# The phony parent always needs a recipe; verify both concrete child builds.
for name, defines in [('park', '-DTOMO_MDBQSBR_LIVE_PARK'),
                      ('no-wake', '-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
    argv = ['make', '-q', 'BUILD_ROOT=build/mdbqsbr2-' + name,
            'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread ' + defines, 'all']
    result = subprocess.run(argv, cwd=ROOT)
    freshness.append(dict(target='mdbqsbr2-' + name, argv=argv, rc=result.returncode))
(OUT / 'freshness.json').write_text(json.dumps(freshness, indent=2) + '\n')
assert all(row['rc'] == 0 for row in freshness), 'stale build'
# Nine advertised physical server CPUs meet the planner's sixteen-CPU minimum;
# its sole correctness slot actually binds servers to 80-87, leaving 88 unused.
run('gate', ['tests/gate.sh', 'quick', '--server-cores', '80-88', '--server-smt', '',
             '--load-cores', '89-95', '--load-smt', '', '--ports', '23800-23877',
             '--candidate-binary', str(ROOT / 'build/tomokv')],
    dict(ENV, GATE_ONLY_JOBS='reorder_identity moverfix'))
# Keep scheduler self-tests free of this lane's compilation/live-test contention.
run('gates-test', ['taskset', '-c', '89-95', 'python3', 'tests/gates_test.py'])
paths = ['build/moverfix/pre/tomokv', 'build/tomokv', 'build/moverfix/pad-a/tomokv']
(OUT / 'arms.json').write_text(json.dumps({path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                       for path in paths}, indent=2) + '\n')
assert all(row['rc'] == 0 for row in rows), 'verification failure; all statuses retained'
