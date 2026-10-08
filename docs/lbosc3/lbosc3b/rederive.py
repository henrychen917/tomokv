#!/usr/bin/env python3
"""Reproduce TU-local lbosc3b compiler budgets; compare code, never execute it."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf, HOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('budgets', nargs='+', type=int)
    parser.add_argument('--db0', action='store_true')
    parser.add_argument('--auto', type=int)
    parser.add_argument('--single', type=int)
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    out = ROOT / 'build/lbosc3/lbosc3b/budgets'
    out.mkdir(parents=True, exist_ok=True)
    pre = ROOT / 'build/lbosc3/PRE' / ('db0/src/main.o' if args.db0 else 'src/main.o')
    elf = Elf(pre)
    functions = elf.functions()
    names = list(functions)
    demangled = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
    before = {n: (d, elf.canonical(functions[n])) for n, d in zip(names, demangled) if HOT.search(d)}
    def trial(budget):
        label = ('db0-main-' if args.db0 else 'main-') + str(budget)
        if args.auto is not None: label += '-a' + str(args.auto)
        if args.single is not None: label += '-s' + str(args.single)
        target = out / (label + '.o')
        command = ['taskset', '-c', '112-127', 'g++', '-std=c++20', '-O2', '-g0',
                   '-Wall', '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
                   '--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={budget}', '-I.']
        command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if args.db0 else ['-DTOMO_DUAL_DATABASE']
        if args.auto is not None: command += ['--param', f'max-inline-insns-auto={args.auto}']
        if args.single is not None: command += ['--param', f'max-inline-insns-single={args.single}']
        command += ['-c', 'src/main.cc', '-o', str(target)]
        with (out / (label+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        after = Elf(target)
        emitted = after.functions()
        changed = [d for n,(d,canonical) in before.items()
                   if n not in emitted or after.canonical(emitted[n]) != canonical]
        report = dict(command=command, total=len(before), matched=len(before)-len(changed), changed=changed,
                      base=(ROOT/'build/lbosc3/PRE/commit').read_text().strip(),
                      pre_sha256=hashlib.sha256(pre.read_bytes()).hexdigest(),
                      post_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        (out/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        print(label,report['matched'],report['total'],changed,flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(trial,args.budgets))


if __name__ == '__main__': main()
