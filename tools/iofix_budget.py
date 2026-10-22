#!/usr/bin/env python3
"""Compile-only IO refinement budget trials, constrained to the lane's CPUs."""
import argparse
import concurrent.futures
import json
import re
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
    base = ROOT / 'build/iofix/PRE' / args.unit
    old = inventory(base)
    work = ROOT / 'build/iofix/budgets' / args.label / args.unit.replace('/', '_')
    out = ROOT / 'docs/iofix/budgets' / args.label / args.unit.replace('/', '_')
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    source = args.unit.removeprefix('db0/').removesuffix('.o') + '.cc'

    def trial(value):
        obj = work / f'{value}.o'
        command = ['taskset', '-c', '80-95', 'g++', '-std=c++20', '-O2', '-g0',
                   '-Wall', '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
                   '--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={value}', '-I.']
        if args.unit.startswith('db0/'):
            command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        elif source == 'src/main.cc':
            command += ['-DTOMO_DUAL_DATABASE']
        command += [f'-fdump-ipa-inline={work / str(value)}.inline', '-c', source, '-o', str(obj)]
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
