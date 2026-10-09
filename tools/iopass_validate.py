#!/usr/bin/env python3
"""Run existing serverless gate witnesses directly; never run gate.sh or a server."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/iopass/validation'
OUT.mkdir(parents=True, exist_ok=True)
assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin witnesses to CPUs 112-127'
# The admission witness builds fused placement from affinity and asserts the gate's
# eight-core geometry. A wider allowed mask is not equivalent even without workers.
allowed = sorted(os.sched_getaffinity(0))
assert len(allowed) >= 8, 'serverless fixtures require eight allowed CPUs'
os.sched_setaffinity(0, allowed[:8])

jobs = []
def unit(name, *args, expected=0):
    jobs.append((name + ('-' + '-'.join(args) if args else ''), ['build/' + name, *args], expected))
def py(name, *args):
    jobs.append((name.removesuffix('.py') + ('-' + '-'.join(args) if args else ''),
                 [sys.executable, 'tests/' + name, *args], 0))

for name in ('config-parser-test', 'flipctl-unit', 'read-local-ring-unit', 'read-local-write-ring-unit',
             'rlfence-unit', 'waits-unit', 'climon-mask-unit', 'shutdown-unit', 'netcap-unit',
             'multidb-unit', 'multidb-boundary-unit'):
    unit(name)
unit('climon-mask-old-unit', expected=1)
for row in ('watch', 'lifetime', 'drain', 'route', 'snapshot', 'config', 'notify'):
    unit('core-concurrency-unit', row)
for mode in ('1s', '2s'):
    unit('rltopo-unit', mode)
for group in ('publication', 'watch', 'metadata'):
    py('exbatch_checks.py', group)
py('lbplanner_checks.py')
py('persistfix_checks.py')
for group in ('policy', 'phase', 'stages', 'split-phase'):
    py('wb_rule_checks.py', 'check', group)
for group in ('clauses', 'paths'):
    py('wbland_checks.py', 'check', group)
for group in ('flush', 'headers'):
    py('flushfix_checks.py', 'check', group)
py('mdbqsbr_checks.py', 'build/mdbqsbr-unit')
py('multidb_serial.py', '--self-test')
for row in ('admission', 'closure', 'script_keys', 'rename_overlay', 'write_latest', 'script_apply',
            'post_apply_probe', 'lua_conversion', 'watch_parent', 'watch_cycle', 'mset_arity',
            'watch_oom', 'lua_lines', 'library_limit', 'stage_flag', 'instruction_limit'):
    unit('atomic-survivors-unit', row)
for row in ('streams', 'zpop', 'notify-oom', 'notify-retry', 'flush', 'output', 'pubsub', 'receive', 'config', 'hexpire-oom'):
    unit('netcmd-unit', row)
for row in ('unlinked', 'randomkey', 'rehash', 'rollback', 'snapshot-eviction', 'aof-eviction',
            'intents', 'imported-hash', 'field-index-failure', 'hash-bytes'):
    unit('store-regression', row)
unit('store-regression-sidecar', 'deadline-sidecar')
unit('rehash-waits-unit', 'retirement')
py('splitlocal_checks.py', 'check')
py('r7shadow_sync.py')
py('read_local_lane.py', '--self-test', 'mget-fence')
py('docs_drift.py', '--self-test')
py('connreset_harness_test.py')
jobs.append(('connreset-negative', [sys.executable, 'tests/connreset_harness_test.py', '--negative-control'], 1))
for name in ('reorder-engagement-unit', 'reorder-engagement-unit-db0'):
    py('reorder_receipt.py', 'build/' + name, 'build/iopass-validation-' + name, '--engagement')

results = []
for name, command, expected in jobs:
    log = OUT / (name.replace('/', '_') + '.log')
    print('RUN', name, flush=True)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1', UBSAN_OPTIONS='halt_on_error=1')
    with log.open('w') as stream:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=stream, timeout=180)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    passed = code == expected
    results.append(dict(name=name, command=command, expected=expected, returncode=code, passed=passed,
                        log=str(log.relative_to(ROOT))))
    print('PASS' if passed else 'FAIL', name, code, flush=True)
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
failed = [row['name'] for row in results if not row['passed']]
print('RESULT', len(results) - len(failed), '/', len(results), 'failed:', failed, flush=True)
sys.exit(bool(failed))
