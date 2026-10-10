#!/usr/bin/env python3
"""Focused aoffix2 proof runner; no gate or throughput benchmark invocation.

All processes inherit taskset 112-127; target 112-119, oracle 120, load 121-127.
Every command/result is retained, including failed attempts. Run from the worktree.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import aoffix2 as h


def run(label, cmd, env=None, timeout=600, check=True):
    log = OUT / (label + '.log')
    assert not log.exists(), log
    start = time.monotonic()
    before = Path('/proc/loadavg').read_text().strip()
    command = ['taskset', '-c', '112-127', *map(str, cmd)]
    with log.open('w') as out:
        try:
            result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
                                    env=env, timeout=timeout)
            rc = result.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    row = dict(label=label, command=command, rc=rc, seconds=time.monotonic() - start,
               load_before=before, load_after=Path('/proc/loadavg').read_text().strip())
    ROWS.append(row)
    (OUT / 'commands.json').write_text(json.dumps(ROWS, indent=2) + '\n')
    print(label, rc, flush=True)
    if check:
        assert rc == 0, log
    return rc


def row_proof():
    for engine in ('uring', 'epoll'):
        for mode in ('1s', '2s'):
            for case in ('snapshot', 'filename', 'error', 'tickets', 'exec_tickets',
                         'resurrection', 'rewrite_fail2', 'manifest_missing',
                         'latency-everysec', 'latency-always'):
                label = f'{case}-{mode}-{engine}'
                actual = 'latency' if case.startswith('latency-') else case
                extra = ['--policy', case.split('-')[1]] if actual == 'latency' else []
                run(label, ['python3', 'tests/aoffix2.py', actual, '--binary', ARGS.binary,
                            '--cores', '112-119', '--port', '25000', '--mode', mode,
                            '--engine', engine, '--artifacts', WORK / label, *extra], check=False)
        for case in ('large', 'large_placed'):
            label = f'{case}-1s-{engine}'
            run(label, ['python3', 'tests/aoffix2.py', case, '--binary', ARGS.binary,
                        '--cores', '112-119', '--port', '25000', '--mode', '1s',
                        '--engine', engine, '--artifacts', WORK / label], check=False)
    assert len(ROWS) == 44
    assert all(row['rc'] == (1 if ARGS.negative else 0) for row in ROWS), OUT / 'commands.json'


def timings():
    cells = []
    for mode in ('1s', '2s'):
        for shape in ('seq', 'conns'):
            for policy in ('off', 'no', 'everysec', 'always'):
                cells.append((f'{mode}-{shape}-{policy}', ['latency', '--mode', mode,
                    '--shape', shape, '--policy', policy, '--samples', '200' if shape == 'seq' else '20']))
    for policy in ('off', 'no', 'everysec', 'always'):
        cells.append((f'defaults-{policy}', ['latency', '--shape', 'defaults', '--policy', policy,
                                          '--samples', '20']))
    cells.append(('2s-conns-everysec-ratio1to1', ['latency', '--shape', 'conns',
                  '--policy', 'everysec', '--ratio', '1:1', '--samples', '20']))
    cells.append(('2s-gate-hol', ['gate_hol']))
    for mode in ('1s', '2s'):
        cells.append((f'bgsave-{mode}', ['bgsave', '--mode', mode]))
        cells.append((f'tlswake-{mode}', ['tlswake', '--mode', mode, '--tls-port', '25002']))
    for label, options in cells:
        run(label, ['python3', 'tests/aoffix2.py', *options, '--binary', ARGS.binary,
                    '--cores', '112-119', '--port', '25001', '--observe',
                    '--artifacts', WORK / label], check=False)
    assert all(row['rc'] == 0 for row in ROWS)


def units():
    gate = (ROOT / 'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb()', 1)[0]
    names = re.search(r'for target in (.*?); do', body).group(1).split()
    assert len(names) == 28
    run('production-units-build', ['make', '-k', '-j16', *['build/' + name for name in names]],
        timeout=7200, check=False)
    for name in names:
        run('fresh-' + name, ['make', '-q', 'build/' + name], check=False)
    run('mdbqsbr-live-arms-build', ['make', '-j16', 'mdbqsbr-live-arms'], timeout=7200, check=False)
    assert all(row['rc'] == 0 for row in ROWS)


def battery_chain(label, action):
    try:
        action()
    except Exception:
        trace = traceback.format_exc()
        (OUT / (label + '-chain-error.log')).write_text(trace)
        ROWS.append(dict(label=label + '-chain-error', rc=1, error=trace))
        (OUT / 'commands.json').write_text(json.dumps(ROWS, indent=2) + '\n')
        print(trace, flush=True)


def batteries():
    for engine in ('uring', 'epoll'):
        for mode in ('1s', '2s'):
            geometry = f'{mode}-{engine}'
            h.ARGS = SimpleNamespace(binary=ARGS.binary, cores='112-119', port=25003,
                                     mode=mode, engine=engine, ratio='6:2', oracle=False)
            h.ARGS.artifacts = WORK / geometry
            h.ARGS.artifacts.mkdir(parents=True)
            for atomic in ('0', '1'):
                opt = h.aof('no') + ['--atomic', atomic]
                for name in ('aof', 'rewrite', 'triggers', 'torn', 'frame'):
                    if name == 'torn' and atomic != '1':
                        continue  # This existing battery requires --atomic 1.
                    prefix = f'{geometry}-{atomic}-{name}'
                    def chain():
                        data = h.ARGS.artifacts / f'{name}-{atomic}'
                        state = h.ARGS.artifacts / f'{name}-{atomic}.json'
                        def live(script, phase_args, suffix):
                            run(prefix + '-' + suffix, ['python3', 'tests/' + script + '.py',
                                '127.0.0.1', '25003', *phase_args], timeout=120)
                        with h.Server(opt, data=data) as s:
                            assert s.ready, s.logpath
                            if name == 'aof':
                                live('aof', ['populate', state], 'populate')
                                live('aof', ['loadaof', state], 'loadaof')
                                live('aof', ['snapshot', data / 'dump.tomo'], 'snapshot')
                                s.stop(signal.SIGKILL)
                            elif name == 'rewrite':
                                live('aof_rewrite', ['populate', state, '2048'], 'populate')
                                live('aof_rewrite', ['rewrite', state, data], 'rewrite')
                                live('aof_rewrite', ['manifest', data], 'manifest')
                            elif name == 'triggers':
                                live('aof_rewrite_triggers', ['run', state, data, atomic], 'run')
                            elif name == 'torn':
                                live('aof_torn_group', ['prepare', state], 'prepare')
                                s.p.wait(timeout=10)
                                assert s.p.returncode == -signal.SIGKILL
                            else:
                                live('aof_frame_order', [data / 'appendonlydir'], 'run')
                        with h.Server(opt, data=data) as s:
                            assert s.ready, s.logpath
                            if name == 'aof':
                                live('aof', ['verify', state], 'verify')
                                live('aof', ['snapshot', data / 'dump.tomo'], 'snapshot-post')
                                def model(suffix):
                                    text = (OUT / (prefix + '-' + suffix + '.log')).read_text()
                                    return next(line for line in text.splitlines() if line.startswith('SNAPSHOT BYTE MODEL:'))
                                assert model('snapshot') == model('snapshot-post')
                            elif name == 'rewrite':
                                live('aof_rewrite', ['verify', state], 'verify')
                            elif name == 'triggers':
                                live('aof_rewrite_triggers', ['verify', state, data, atomic], 'verify')
                            elif name == 'torn':
                                live('aof_torn_group', ['verify', state], 'verify')
                                live('aof_torn_group', ['scan', data / 'appendonlydir/appendonly.aof.1.incr.tomo'], 'scan')
                    battery_chain(prefix, chain)
            for policy in ('no', 'everysec', 'always'):
                prefix = f'{geometry}-fsync-{policy}'
                def chain():
                    state = h.ARGS.artifacts / f'fsync-{policy}.json'
                    data = h.ARGS.artifacts / f'fsync-{policy}'
                    opt = h.aof(policy) + ['--atomic', '1']
                    with h.Server(opt, data=data) as s:
                        run(prefix + '-populate', ['python3', 'tests/aof_fsync.py', '127.0.0.1',
                            '25003', 'populate', state, policy, '512'], timeout=120)
                        s.stop(signal.SIGKILL)
                    if policy == 'everysec':
                        incr = data / 'appendonlydir/appendonly.aof.1.incr.tomo'
                        with incr.open('r+b') as out:
                            out.truncate(incr.stat().st_size - 7)
                    with h.Server(opt, data=data):
                        run(prefix + '-verify', ['python3', 'tests/aof_fsync.py', '127.0.0.1',
                            '25003', 'verify', state, policy, '512'], timeout=120)
                battery_chain(prefix, chain)
            for case in ('kill', 'term'):
                prefix = f'{geometry}-persistfix-{case}'
                run(prefix, ['python3', 'tests/persistfix.py', '--binary', ARGS.binary,
                    '--mode', mode, '--case', case, '--net-io', engine, '--cores', '112-119',
                    '--ratio', '6:2', '--port', '25003', '--artifacts', WORK / prefix], timeout=120, check=False)

    assert all(row['rc'] == 0 for row in ROWS), OUT / 'commands.json'


def differ():
    suites, seeds = OUT / 'suites.txt', OUT / 'seeds.txt'
    suites.write_text('psfix\nmulti\nxshard\nservertail\n')
    seeds.write_text('7\n19\n20\n23\n')
    for geometry in ('split', 'armed-fused'):
        env = dict(os.environ, REDIS74_ROOT='/tmp/claude-1000/redis74',
                   GATE_LOAD_CORES='121-127', GATE_DIFFER_ORACLE_CORES='120',
                   GATE_DIFFER_GEOMETRY=geometry, GATE_DIFFER_PROOF_SUITES=str(suites),
                   GATE_DIFFER_PROOF_SEEDS=str(seeds), GATE_DIFFER_OUT=str(WORK / geometry))
        run(geometry, ['tests/differ_gate.sh', ARGS.binary, '25004', '25005', '112-119', '6:2'],
            env=env, timeout=3600, check=False)
    assert all(row['rc'] == 0 for row in ROWS)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('stage', choices=('rows', 'timings', 'units', 'batteries', 'differ'))
parser.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--negative', action='store_true')
ARGS = parser.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'run under taskset -c 112-127'
os.chdir(ROOT)
ARGS.binary = ARGS.binary.resolve()
OUT = ARGS.output.resolve()
OUT.mkdir(parents=True, exist_ok=False)
WORK = ROOT / 'build/aoffix2' / OUT.name
WORK.mkdir(parents=True, exist_ok=False)
ROWS = []
dict(rows=row_proof, timings=timings, units=units, batteries=batteries, differ=differ)[ARGS.stage]()
