#!/usr/bin/env python3
"""Compile-only IO refinement budget trials, constrained to the lane's CPUs."""
import argparse
import concurrent.futures
import json
import re
import shlex
from pathlib import Path
import subprocess
import time

from ccfix4_budget import inventory, compare

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('values', nargs='+', type=int)
    p.add_argument('--unit', default='src/core/rl2s.o')
    p.add_argument('--source-root', type=Path, default=ROOT)
    p.add_argument('--label', default='post')
    args = p.parse_args()
    base = ROOT / 'build/latencyfix/pre' / args.unit
    old = inventory(base)
    work = ROOT / 'build/latencyfix/budgets' / args.label / args.unit.replace('/', '_')
    out = ROOT / 'docs/latencyfix/budgets' / args.label / args.unit.replace('/', '_')
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    source = args.unit.removeprefix('db0/').removesuffix('.o') + '.cc'
    recipes = subprocess.check_output(['make', '-Bn', 'build/' + args.unit],
                                      cwd=args.source_root, text=True).splitlines()
    recipes = [shlex.split(line) for line in recipes if line.startswith('g++ ')]
    command_template, = [cmd for cmd in recipes if '-c' in cmd and source in cmd and
                         cmd[-1] == 'build/' + args.unit]

    def trial(value):
        obj = work / f'{value}.o'
        command = ['-g0' if x == '-g' else f'large-unit-insns={value}'
                   if x.startswith('large-unit-insns=') else x for x in command_template]
        if not any(x.startswith('large-unit-insns=') for x in command):
            command += ['--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={value}']
        command[command.index('-o') + 1] = str(obj)
        command = ['taskset', '-c', '80-95', *command,
                   f'-fdump-ipa-inline={work / str(value)}.inline']
        start = time.monotonic()
        with (work / f'{value}.log').open('w') as log:
            subprocess.run(command, cwd=args.source_root, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = dict(value=value, unit=args.unit, command=command, source_root=str(args.source_root),
                      seconds=time.monotonic() - start, **compare(old, inventory(obj)))
        dump = work / f'{value}.inline'
        result['initial_inline_unit'] = int(re.search(r'Starting with size (\d+)', dump.read_text())[1])
        dump.unlink()
        (out / f'{value}.json').write_text(json.dumps(result, indent=2) + '\n')
        print(value, 'changed', result['changed'], 'hot', result['hot_changed'], flush=True)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(trial, args.values))


if __name__ == '__main__':
    main()
