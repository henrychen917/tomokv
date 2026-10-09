#!/usr/bin/env python3
"""Run the existing serverless persistfix schedules against each AOF budget arm."""
from pathlib import Path
import json
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'tools'))
import persistfix_controls

base = root / 'build/deadswitch/pre'
work = root / 'build/deadswitch/persistfix'
work.mkdir(exist_ok=True)
(root / 'build/persistfix').mkdir(exist_ok=True)
flags = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
         '-DTOMO_JEMALLOC', '-DTOMO_PERSISTFIX_TEST', '-I.', '-iquote', 'src/persist']
objects = [str(p) for p in sorted((base / 'src').rglob('*.o'))
           if p not in (base / 'src/main.o', base / 'src/persist/aof.o')]
unit = work / 'unit.o'
rows = []
source = subprocess.check_output(['git', 'show',
    'deadswitch-before-20261009:src/persist/aof.cc'], cwd=root, text=True)
with (work / 'build.log').open('w') as log:
    subprocess.run(flags + ['-c', 'tests/persistfix_unit.cc', '-o', str(unit)],
                   cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    for budget in (16, 1, 4096):
        directory = work / str(budget)
        original = directory / 'src/persist/aof.cc'
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_text(source.replace('kWriterFramesPerPass = 16;',
                                           f'kWriterFramesPerPass = {budget};'))
        persistfix_controls.ROOT = directory
        for control in ('current', 'old-ack', 'old-close', 'no-refusal'):
            copied = original
            if control != 'current':
                copied = directory / f'{control}.cc'
                persistfix_controls.emit(control, copied)
            obj = directory / f'{control}.o'
            binary = directory / control
            subprocess.run(flags + ['-c', str(copied), '-o', str(obj)], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(['g++', '-pthread', str(unit), str(obj), *objects,
                            '-o', str(binary), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'],
                           cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
            cases = ('ack', 'remote', 'shutdown', 'refusal', 'frameorder') if control == 'current' else ({
                'old-ack': ('ack',), 'old-close': ('shutdown',), 'no-refusal': ('refusal',)}[control])
            for case in cases:
                result = subprocess.run([str(binary), case], cwd=root, text=True,
                                        capture_output=True, timeout=20)
                # Preserve the suite's actual result; do not hide the budget-1 arming failure.
                row = dict(budget=budget, control=control, case=case, status=result.returncode,
                           stdout=result.stdout, stderr=result.stderr)
                rows.append(row)
                print(json.dumps(row), flush=True)
                (root / 'docs/deadswitch/02-persistfix-schedules.json').write_text(
                    json.dumps(rows, indent=2) + '\n')
assert len(rows) == 24
for row in rows:
    if row['control'] == 'current' and not (row['budget'] == 1 and row['case'] == 'frameorder'):
        assert row['status'] == 0, row
    elif row['control'] == 'current':
        assert row['status'] == 1 and 'ready GCMT and OPEN large record coexist' in row['stderr'], row
    else:
        expected = {'old-ack': 'acknowledgement cannot precede post',
                    'old-close': 'writer cannot close before producers stop posting',
                    'no-refusal': 'refused post appears in persistence report'}[row['control']]
        assert row['status'] == 1 and expected in row['stderr'], row
