#!/usr/bin/env python3
"""Lane-local correctness proof runner; never runs the full gate or a performance benchmark."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/hexpread/final'
PIN = ['taskset', '-c', '96-111']
sys.path.insert(0, str(ROOT / 'tests'))


def run(label, command, *, expected=0, env=None):
    command = PIN + list(map(str, command))
    with (OUT / (label + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    row = dict(label=label, command=command, exit_code=result.returncode, expected=expected,
               matched=result.returncode == expected)
    print(label, result.returncode, 'expected', expected, flush=True)
    return row


def functional():
    rows = []
    for arm, binary in [('pre', ROOT / 'build/hexpread-pre/tomokv'), ('post', ROOT / 'build/tomokv')]:
        for mode in ('1s', '2s'):
            for case in ('torn', 'replies', 'deferred', 'object'):
                label = f'{arm}-{mode}-{case}'
                cmd = ['python3', 'tests/objectpread.py' if case == 'object' else 'tests/hexpread.py',
                       '--binary', binary, '--artifacts', OUT / label, '--mode', mode,
                       '--cores', '96-103', '--port', '25800', '--ratio', '6:2']
                if case != 'object':
                    cmd += ['--case', case, '--policy', 'always']
                rows.append(run(label, cmd, expected=1 if arm == 'pre' else 0))
    for mode in ('1s', '2s'):
        for aof in ('no', 'yes'):
            label = f'probe-post-{mode}-aof-{aof}'
            rows.append(run(label, ['python3', 'docs/hexpread/repro/probe.py', '--binary',
                'build/tomokv', '--artifacts', OUT / label, '--mode', mode, '--appendonly', aof]))
        for atomic in (0, 1):
            label = f'common-{mode}-atomic{atomic}'
            rows.append(run(label, ['python3', 'docs/hexpread/common.py', '--binary', 'build/tomokv',
                '--artifacts', OUT / label, '--mode', mode, '--cores', '96-103', '--port', '25802',
                '--atomic', atomic, '--compare', 'docs/hexpread/common-oracle-resp3/common.json']))
    for geometry in ('split', 'armed-fused'):
        env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis74',
                   GATE_LOAD_CORES='105-111', GATE_DIFFER_ORACLE_CORES='104',
                   GATE_DIFFER_GEOMETRY=geometry,
                   GATE_DIFFER_PROOF_SUITES=str(ROOT / 'docs/hexpread/differ-suites.txt'),
                   GATE_DIFFER_PROOF_SEEDS=str(ROOT / 'docs/hexpread/differ-seeds.txt'),
                   GATE_DIFFER_OUT=str(OUT / ('differ-' + geometry)))
        row = run('differ-' + geometry, ['tests/differ_gate.sh', ROOT / 'build/tomokv',
                    '25810', '25811', '96-103', '6:2'], env=env)
        row['environment'] = {k: v for k, v in env.items() if k.startswith('GATE_') or k == 'REDIS74_ROOT'}
        rows.append(row)
    rows.append(run('gates-test', ['python3', 'tests/gates_test.py']))
    rows.append(run('gate-shell-syntax', ['bash', '-n', 'tests/gate.sh']))
    return rows


def batteries():
    import aoffix2 as h
    rows = []
    for mode in ('1s', '2s'):
        artifacts = OUT / ('batteries-' + mode)
        artifacts.mkdir()
        h.ARGS = SimpleNamespace(binary=ROOT / 'build/tomokv', artifacts=artifacts,
            mode=mode, cores='96-103', ratio='6:2', port=25820, oracle=False, engine='uring')
        # Keep the same server for all three batteries, as job_atomic_batteries does.
        with h.Server(['--atomic', '1']) as server:
            assert server.ready
            for battery in ('torn', 'ryow', 'hazards'):
                cmd = ['python3', f'tests/atomic_{battery}.py', '127.0.0.1', '25820']
                if battery == 'torn':
                    cmd += ['--release-build']
                rows.append(run(f'atomic-{mode}-{battery}', cmd))
        rows.append(dict(label=f'atomic-{mode}-shutdown', exit_code=server.p.returncode,
                         expected=0, matched=server.p.returncode == 0, log=str(server.logpath)))
    return rows


def builds():
    prior = json.loads((ROOT / 'docs/hexpread/production-units.json').read_text())
    targets = prior['command'][6:]
    assert len(targets) == 29 and all(t.startswith('build/') for t in targets)
    rows = [run('production-units-build', ['make', '-k', '-j8'] + targets)]
    rows.append(run('mdbqsbr-live-build', ['make', '-j8', 'mdbqsbr-live-arms']))
    rows.append(dict(label='freshness', targets={t: subprocess.run(PIN + ['make', '-q', t],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode for t in targets}))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('functional', 'batteries', 'builds'))
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = globals()[a.phase]()
    document = dict(phase=a.phase, binary_sha256=hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest(), rows=rows)
    (OUT / (a.phase + '.json')).write_text(json.dumps(document, indent=2) + '\n')
    assert all(r.get('matched', all(v == 0 for v in r.get('targets', {}).values())) for r in rows), document


if __name__ == '__main__':
    main()
