#!/usr/bin/env python3
"""Compile-only search for the touched IO translation units' PRE hot-body budgets."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

from ccfix4_budget import inventory, compare

ROOT = Path(__file__).resolve().parents[1]
BASE = {
    'src/main.o': 146401,
    'db0/src/main.o': 146203,
    'src/core/genthread.o': 128865,
    'db0/src/core/genthread.o': 128910,
    'src/core/rl2s.o': 161715,
    'db0/src/core/rl2s.o': 161680,
    'db0/src/core/reorder.o': 147304,
    'db0/src/cmd/t_server.o': 31582,
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--objects', nargs='+', default=list(BASE))
    p.add_argument('--deltas', nargs='+', type=int, required=True)
    p.add_argument('--jobs', type=int, default=8)
    a = p.parse_args()
    out = ROOT / 'build/deadcode2/budgets-release'
    out.mkdir(parents=True, exist_ok=True)
    baseline = {name: inventory(ROOT / 'build/deadcode2/PRE' / name) for name in a.objects}
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD:src'], text=True).strip()

    def trial(pair):
        name, delta = pair
        budget = BASE[name] + delta
        dest = out / tree[:12] / name.replace('/', '_') / str(budget)
        dest.mkdir(parents=True, exist_ok=True)
        receipt = dest / 'result.json'
        if receipt.exists():
            data = json.loads(receipt.read_text())
            assert data['tree'] == tree, 'stale budget trial'
            return data
        cmd = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
               '-pthread', '-DTOMO_JEMALLOC', '--param', 'inline-unit-growth=0', '--param',
               f'large-unit-insns={budget}', '-I.']
        if name.startswith('db0/'):
            cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        elif name == 'src/main.o':
            cmd += ['-DTOMO_DUAL_DATABASE']
        if name == 'db0/src/core/genthread.o':
            cmd += ['-Wa,--defsym,tomo_rlfence_text_pad=16']
        source = name.removeprefix('db0/').removesuffix('.o') + '.cc'
        cmd += ['-c', source, '-o', str(dest/'unit.o')]
        with (dest/'compile.log').open('w') as f:
            subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
        data = dict(object=name, delta=delta, budget=budget, tree=tree, command=cmd,
                    **compare(baseline[name], inventory(dest/'unit.o')))
        receipt.write_text(json.dumps(data, indent=2)+'\n')
        print(name, budget, 'hot', data['hot_changed'], 'bytes', data['hot_differing_bytes'],
              'all',data['changed'], flush=True)
        return data

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        rows = list(pool.map(trial, [(name, d) for name in a.objects for d in a.deltas]))
    for name in a.objects:
        best = min((r for r in rows if r['object'] == name),
                   key=lambda r:(r['hot_changed'],r['hot_differing_bytes'],r['changed']))
        print('BEST',name,best['budget'],best['hot_changed'],best['hot_differing_bytes'],best['changed'])


if __name__ == '__main__':
    main()
