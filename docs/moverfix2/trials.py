#!/usr/bin/env python3
"""Compile-only moverfix2 budget trials; compare every emitted xshard body."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ccfix_audit
from lbstall_artifacts import Elf, HOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(elf):
    functions = elf.functions()
    names = sorted(functions)
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    return {symbol: (name, functions[symbol], elf.canonical(functions[symbol]))
            for symbol, name in zip(names, labels)}


def compare(old, path):
    new = inventory(Elf(path))
    rows = []
    for symbol in sorted(old.keys() | new.keys()):
        a, b = old.get(symbol), new.get(symbol)
        if a and b and a[2] == b[2]:
            continue
        name = (a or b)[0]
        rows.append(dict(symbol=symbol, name=name, hot=bool(HOT.search(name)),
                         before_size=a[1]['size'] if a else 0,
                         trial_size=b[1]['size'] if b else 0))
    r7 = {symbol: dict(name=name, size=body['size'])
          for symbol, (name, body, _) in new.items()
          if 'xshard_execute(' in name and
          ('atomic_for_each_unique_key<' in name or 'FlatStore::scan<' in name)}
    return dict(changed=len(rows), hot_changed=sum(r['hot'] for r in rows),
                r7_bodies=r7, changes=rows)


def compile_one(item):
    namespace, budget, dump = item
    unit = ('db0/' if namespace == 'db0' else '') + 'src/cmd/xshard.o'
    label = f'{namespace}-{budget}'
    obj = ROOT / 'build/moverfix2/trials' / (label + '.o')
    command_text = subprocess.check_output(['make', '-Bn', 'build/' + unit], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in command_text.splitlines()
                if line.startswith('g++ ') and ' -c ' in line]
    command, = [args for args in commands if args[args.index('-o') + 1] == 'build/' + unit]
    index, = [i for i, arg in enumerate(command) if arg.startswith('large-unit-insns=')]
    command[index] = 'large-unit-insns=' + str(budget)
    command[command.index('-o') + 1] = str(obj)
    if dump:
        command += ['-fdump-ipa-inline-details', '-dumpbase', str(obj.with_suffix(''))]
    with (ROOT / 'docs/moverfix2' / (label + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    row = dict(namespace=namespace, budget=budget, command=command, rc=result.returncode)
    if result.returncode:
        return row
    row.update(object_sha256=sha(obj), **compare(BASE[namespace], obj))
    if dump:
        path, = obj.parent.glob(label + '*.inline')
        data = path.read_text()
        row['ipa_start_size'] = int(re.search(r'Starting with size (\d+)', data)[1])
        with gzip.open(path.with_suffix(path.suffix + '.gz'), 'wt') as out:
            out.write(data)
        path.unlink()
    print(f"{label} r7={[v['size'] for v in row['r7_bodies'].values()]} "
          f"changed={row['changed']} hot={row['hot_changed']}", flush=True)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('budgets', nargs='*', type=int,
                        default=[100000, 120000, 127000, 128042, 128350, 128500,
                                 128550, 128600, 128750, 129000, 130000, 140000])
    parser.add_argument('--db0', action='store_true')
    parser.add_argument('--dump', action='store_true')
    args = parser.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(80, 96))
    (ROOT / 'build/moverfix2/trials').mkdir(parents=True, exist_ok=True)
    BASE = {ns: inventory(Elf(ROOT / 'build/moverfix2/current-post' /
                             (('db0/' if ns == 'db0' else '') + 'src/cmd/xshard.o')))
            for ns in ('normal', 'db0')}
    items = [('normal', b, args.dump or b == 128550) for b in args.budgets]
    if args.db0:
        items.append(('db0', 127250, True))
    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(compile_one, items))
    path = ROOT / 'docs/moverfix2' / ('trials-' + '-'.join(str(b) for b in args.budgets) + '.json')
    path.write_text(json.dumps(rows, indent=2) + '\n')
    assert all(row['rc'] == 0 for row in rows), 'compile failure; see per-budget logs'
