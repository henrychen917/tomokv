#!/usr/bin/env python3
"""Compile-only PRE/POST headroom survey for the two affected hot emitters."""
import concurrent.futures
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/blockfix4/pre-source'
OUT = ROOT / 'build/blockfix4/budgets'
DOC = ROOT / 'docs/blockfix4/budgets'
OBJECTS = ['src/main.o', 'db0/src/main.o', 'src/cmd/xshard.o', 'db0/src/cmd/xshard.o']


def trial(case):
    arm, obj, value = case
    source = PRE if arm == 'pre' else ROOT
    target = 'build/' + obj
    lines = subprocess.check_output(['make', '-n', '-B', target], cwd=source, text=True).splitlines()
    cmd = shlex.split(next(s for s in reversed(lines) if s.startswith('g++ ') and s.endswith(' -o ' + target)))
    budget = next(int(x.split('=')[1]) for x in cmd if x.startswith('large-unit-insns='))
    if value is None:
        value = budget
    tag = arm + '-' + obj.replace('/', '_') + '-' + str(value)
    cmd = ['-g0' if x == '-g' else 'large-unit-insns=' + str(value) if x.startswith('large-unit-insns=') else x for x in cmd]
    dest = OUT / (tag + '.o')
    cmd[cmd.index('-o') + 1] = str(dest)
    cmd += ['-fdump-ipa-inline', '-dumpbase', str(OUT / tag)]
    with (DOC / (tag + '.log')).open('w') as log:
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    dump, = OUT.glob(tag + '*.inline')
    with dump.open() as f:
        unit = next(int(m[1]) for line in f if (m := re.search(r'Starting with size (\d+)', line)))
    dump.unlink()
    row = dict(arm=arm, object=obj, budget=value, unit=unit, command=cmd, output=str(dest))
    print(arm, obj, value, unit, flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True); DOC.mkdir(parents=True, exist_ok=True)
    phase = sys.argv[1]
    if phase == 'initial':
        cases = [(arm, obj, None) for arm in ['pre', 'post'] for obj in OBJECTS]
    else:
        rows = json.loads((DOC / 'initial.json').read_text())
        by = {(r['arm'], r['object']): r for r in rows}
        cases = [('post', obj, by['pre', obj]['budget'] + by['post', obj]['unit'] - by['pre', obj]['unit']) for obj in OBJECTS]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(trial, cases))
    (DOC / (phase + '.json')).write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
