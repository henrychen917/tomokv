#!/usr/bin/env python3
"""Compile-only per-unit budget re-derivation; never executes a server."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'tools'))
import ccfix_audit  # Includes resolved code-address normalization.
from lbstall_artifacts import Elf, HOT

assert set(os.sched_getaffinity(0)) <= set(range(80, 96))
out = root / 'build/moverfix/budgets'
out.mkdir(parents=True, exist_ok=True)
report = root / 'docs/moverfix/identity-budgets'
report.mkdir(parents=True, exist_ok=True)
logs = {'pre': root / 'docs/moverfix/pre-build.log',
        'post': root / 'docs/moverfix/post-build.log'}
sources = {'pre': root / 'build/moverfix/pre-source', 'post': root}
units = ('src/cmd/xshard.o', 'db0/src/cmd/xshard.o')


def command(arm, unit):
    for line in logs[arm].read_text().splitlines():
        if line.startswith('g++ ') and ' -c ' in line:
            args = shlex.split(line)
            target = args[args.index('-o') + 1]
            if target.endswith('/' + unit) and 'publishfix-unit-objects' not in target:
                return args
    raise AssertionError((arm, unit))


def compile_one(arm, unit, budget=None, dump=False):
    label = unit.replace('/', '_') + '-' + arm + '-' + str(budget or 'base')
    obj = out / (label + '.o')
    args = command(arm, unit)
    original, = [x for x in args if x.startswith('large-unit-insns=')]
    if budget is not None:
        args[args.index(original)] = 'large-unit-insns=' + str(budget)
    args[args.index('-o') + 1] = str(obj)
    if dump:
        args += ['-fdump-ipa-inline', '-dumpbase', str(out / label)]
    args = ['taskset', '-c', '80-95', *args]
    with (out / (label + '.log')).open('w') as log:
        subprocess.run(args, cwd=sources[arm], stdout=log, stderr=subprocess.STDOUT, check=True)
    size = None
    if dump:
        path, = list(out.glob(label + '*.inline'))
        text = path.read_text()
        size = int(re.search(r'Starting with size (\d+)', text)[1])
        with gzip.open(path.with_suffix(path.suffix + '.gz'), 'wt') as f:
            f.write(text)
        path.unlink()
    row = dict(arm=arm, unit=unit, budget=budget or int(original.split('=')[1]),
               start_size=size, object=str(obj), command=args)
    with (report / 'commands.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n')
    return row


def compare(unit, obj):
    before = Elf(root / 'build/moverfix/pre' / unit)
    after = Elf(obj)
    old, new = before.functions(), after.functions()
    names = sorted(old.keys() | new.keys())
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    rows = []
    for symbol, name in zip(names, labels):
        a, b = old.get(symbol), new.get(symbol)
        if a and b and before.canonical(a) == after.canonical(b):
            continue
        direct = any(x in name for x in ('execute_plain_element_mover', 'execute_live_pop', 'xshard_execute(', 'finish_phase2('))
        rows.append(dict(symbol=symbol, name=name, direct=direct, hot=bool(HOT.search(name)),
                         pre_size=a['size'] if a else 0, post_size=b['size'] if b else 0))
    return dict(changed=len(rows), spillover=sum(not r['direct'] for r in rows),
                hot=sum(r['hot'] for r in rows), bodies=rows)


def main():
    # Four source-accurate baseline dumps derive the IPA size delta separately per namespace.
    with ThreadPoolExecutor(max_workers=16) as pool:
        baselines = list(pool.map(lambda x: compile_one(*x, dump=True),
                                 [(arm, unit) for unit in units for arm in ('pre', 'post')]))
    (report / 'sizes.json').write_text(json.dumps(baselines, indent=2) + '\n')
    trials = []
    for unit in units:
        pre, post = [r for r in baselines if r['unit'] == unit]
        assert pre['arm'] == 'pre' and post['arm'] == 'post'
        target = post['budget'] + post['start_size'] - pre['start_size']
        values = sorted({post['budget'], *[target + d for d in (-16, 0, 16)]})
        trials += [('post', unit, value) for value in values]
    with ThreadPoolExecutor(max_workers=16) as pool:
        compiled = list(pool.map(lambda x: compile_one(*x), trials))
    results = []
    for r in compiled:
        result = dict(r, **compare(r['unit'], r['object']))
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('command', 'bodies')}), flush=True)
    (report / 'trials.json').write_text(json.dumps(results, indent=2) + '\n')
    for unit in units:
        options = [r for r in results if r['unit'] == unit]
        best = min(options, key=lambda r: (r['hot'], r['spillover'], r['changed'],
                                          abs(r['budget'] - next(b['budget'] for b in baselines if b['unit'] == unit))))
        print('BEST', unit, best['budget'], 'hot', best['hot'], 'spillover', best['spillover'], flush=True)


if __name__ == '__main__':
    main()
