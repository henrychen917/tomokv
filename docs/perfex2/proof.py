#!/usr/bin/env python3
"""Perfex2 correctness receipts; CPU/port allocation is part of this task."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server


def run(argv, out, env=None, timeout=None):
    argv = list(map(str, argv))
    start = time.monotonic()
    with out.open('w') as log:
        rc = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env=dict(os.environ, **(env or {})), timeout=timeout).returncode
    row = dict(argv=argv, environment=env or {}, exit_code=rc,
               seconds=time.monotonic() - start, log=str(out.relative_to(ROOT)))
    with (out.parent / 'commands.jsonl').open('a') as stream:
        stream.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)
    return row


def direct(a):
    rows = []
    for atomic in (0, 1):
        directory = a.output / f'a{atomic}'
        directory.mkdir()
        with server(a.binary, '112-119', 25100, directory / 'server',
                    ['--ratio', '6:2', '--shards', '16', '--atomic', atomic]):
            for i in range(a.rounds):
                for script in ('expwide', 'infofix'):
                    row = run(['taskset', '-c', '120-127', sys.executable,
                               ROOT / 'tests' / (script + '.py'), '127.0.0.1', '25100'],
                              directory / f'{script}-{i + 1}.log', timeout=300)
                    row.update(atomic=atomic, round=i + 1, battery=script)
                    rows.append(row)
                    if a.stop_on_repro and script == 'infofix' and 'FAIL measured avg_ttl' in (
                            directory / f'{script}-{i + 1}.log').read_text():
                        return rows
    return rows


def gate(a):
    rows = []
    for i in range(a.rounds):
        out = a.output / f'run-{i + 1}.log'
        row = run(['taskset', '-c', '112-127', ROOT / 'tests/gate.sh', 'iteration',
                   '--server-cores', '112-119', '--load-cores', '120-127', '--load-smt', '',
                   '--ports', '25100-25124', '--candidate-binary', a.binary], out,
                  dict(GATE_ONLY_JOBS='feature-split-0 feature-split-1',
                       GATE_LEDGER=str(a.output / f'run-{i + 1}.ledger'),
                       REDIS74_ROOT='/tmp/claude-1000/redis74'))
        match = re.search(r'artifacts: (\S+)', out.read_text())
        assert match, out
        root = Path(match[1])
        row['infofix'] = {}
        for atomic in (0, 1):
            files = list(root.glob(f'jobs/feature-split-{atomic}/**/gate-infofix-{atomic}.txt'))
            assert len(files) == 1, files
            dest = a.output / f'run-{i + 1}-infofix-{atomic}.txt'
            shutil.copyfile(files[0], dest)
            row['infofix'][str(atomic)] = dict(passed='INFOFIX: PASS' in dest.read_text(),
                                              log=str(dest.relative_to(ROOT)))
        rows.append(row)
        print(json.dumps(row['infofix']), flush=True)
        if a.stop_on_repro and any('FAIL measured avg_ttl' in (ROOT / x['log']).read_text()
                                  for x in row['infofix'].values()):
            break
    return rows


def rows(a):
    result = []
    for check in ('clock', 'batch'):
        result.append(run(['taskset', '-c', '112-127', sys.executable,
                           'tests/perfex_checks.py', check, '--binary', a.binary],
                          a.output / f'{check}.log'))
    for mode in ('1s', '2s'):
        result.append(run(['taskset', '-c', '120-127', sys.executable,
                           'tests/perfex_checks.py', 'sampler', '--binary', a.binary,
                           '--port', '25100', '--cores', '112-119', '--mode', mode],
                          a.output / f'sampler-{mode}.log'))
    return result


def units(a):
    body = (ROOT / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1]
    command = body.split('make -k', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r'\bbuild/[\w-]+', command)
    assert targets and len(targets) == len(set(targets))
    (a.output / 'targets.json').write_text(json.dumps(targets, indent=2) + '\n')
    result = [run(['taskset', '-c', '112-127', 'make', '-k', '-j16', *targets],
                  a.output / 'production-units-build.log'),
              run(['taskset', '-c', '112-127', 'make', '-j16', 'mdbqsbr-live-arms'],
                  a.output / 'mdbqsbr-live-arms-build.log')]
    for target in [*targets, 'all']:
        result.append(run(['taskset', '-c', '112-127', 'make', '-q', target],
                          a.output / (Path(target).name + '-fresh.log')))
    result.append(run(['taskset', '-c', '112-127', sys.executable,
                       'tests/storesize_checks.py', 'check-all', 'build/storesize-unit'],
                      a.output / 'storesize.log'))
    return result


def differ(a):
    (a.output / 'suites.txt').write_text('edgetime\nhexpire\n')
    (a.output / 'seeds.txt').write_text('7\n19\n20\n23\n')
    result = []
    for geometry in ('split', 'armed-fused'):
        result.append(run(['taskset', '-c', '112-127', 'tests/differ_gate.sh', a.binary,
                           '25103', '25104', '112-119', '6:2'], a.output / f'{geometry}.log',
                          dict(REDIS74_ROOT='/tmp/claude-1000/redis74', GATE_LOAD_CORES='121-127',
                               GATE_DIFFER_ORACLE_CORES='120', GATE_DIFFER_GEOMETRY=geometry,
                               GATE_DIFFER_OUT=str(a.output / geometry),
                               GATE_DIFFER_PROOF_SUITES=str(a.output / 'suites.txt'),
                               GATE_DIFFER_PROOF_SEEDS=str(a.output / 'seeds.txt'))))
    return result


def wiring(a):
    return [run(['taskset', '-c', '112-127', sys.executable, script], a.output / f'{label}.log')
            for label, script in (('gates-test', 'tests/gates_test.py'),
                                  ('pfconfirm-units', 'docs/pfconfirm/test_confirm.py'))]


def smoke(a):
    digest = hashlib.file_digest(a.binary.open('rb'), 'sha256').hexdigest()
    return [run(['taskset', '-c', '112-127', 'docs/pfconfirm/run.sh', '--smoke',
                 '--only', 'PFKEYSPA.1', '--binary', a.binary, '--sha256', digest,
                 '--port', '25120', '--output', a.output / 'pfconfirm'],
                a.output / 'pfconfirm.log')]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('direct', 'gate', 'rows', 'units', 'differ', 'wiring', 'smoke'))
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--rounds', type=int, default=20)
    p.add_argument('--stop-on-repro', action='store_true',
                   help='negative PRE only: stop after a witnessed avg_ttl failure')
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(112, 128))
    a.binary = a.binary.resolve()
    a.output = a.output.resolve()
    assert a.output.is_relative_to(ROOT)
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'binary.json').write_text(json.dumps(dict(
        binary=str(a.binary), sha256=hashlib.file_digest(a.binary.open('rb'), 'sha256').hexdigest(),
        source=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    ), indent=2) + '\n')
    rows = globals()[a.stage](a)
    (a.output / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
    return any(row['exit_code'] for row in rows)


if __name__ == '__main__':
    raise SystemExit(main())
