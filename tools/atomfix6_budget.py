#!/usr/bin/env python3
"""Compile-only xshard budget trials to preserve the atomic-off instruction path."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('arm', choices=['PRE', 'POST'])
p.add_argument('budgets', nargs='*', type=int)
a = p.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
source = ROOT / 'build/pre-source' if a.arm == 'PRE' else ROOT
out = ROOT / 'build/atomfix6/budgets'; out.mkdir(parents=True, exist_ok=True)
docs = ROOT / 'docs/atomfix6/budgets'; docs.mkdir(parents=True, exist_ok=True)
recipe = subprocess.check_output(['make', '-Bn', 'build/db0/src/cmd/xshard.o'], cwd=source, text=True)
original = shlex.split(next(x for x in reversed(recipe.splitlines()) if x.startswith('g++ ')))
default = int(next(x.split('=')[1] for x in original if x.startswith('large-unit-insns=')))
before = Elf(ROOT / 'build/pre/db0/src/cmd/xshard.o')
symbol = '_ZN8tomo_db014xshard_executeERKNS_4TaskERNS_5ShardERNS_2OpEj'


def trial(value):
    label = f'{a.arm}-{value}'
    dest = out / (label + '.o'); dump = out / (label + '.inline')
    cmd = ['-g0' if x == '-g' else f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x
           for x in original]
    cmd[cmd.index('-o') + 1] = str(dest)
    cmd += [f'-fdump-ipa-inline={dump}']
    with (out / (label + '.log')).open('w') as log:
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    initial = int(re.search(r'Starting with size (\d+)', dump.read_text())[1]); dump.unlink()
    after = Elf(dest)
    row = dict(arm=a.arm, budget=value, initial=initial, command=cmd, output=str(dest),
               execute_size=after.functions()[symbol]['size'],
               execute_identical=before.canonical(before.functions()[symbol]) == after.canonical(after.functions()[symbol]))
    (docs / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    print(label, initial, row['execute_size'], row['execute_identical'], flush=True)
    return row

with concurrent.futures.ThreadPoolExecutor(4) as pool:
    list(pool.map(trial, a.budgets or [default]))
