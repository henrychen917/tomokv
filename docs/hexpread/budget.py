#!/usr/bin/env python3
"""Compile-only inlining-budget trials with the ttlclean relocation-aware checker."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ccfix4_budget import inventory, compare


def allowed(name):
    return any(part in name for part in (
        'cmd_hget', 'cmd_hmget', 'cmd_hexists', 'cmd_hstrlen', 'cmd_hlen', 'cmd_hrandfield',
        'generic_getall', 'cmd_hscan', 'HashReadView', 'hash_read_lookup', 'select_unique',
        'hash_random_bounded', 'hash_ttl_on_access', 'atomic_read_owns_value',
        'std::vector<std::pair<tomo::Slice, tomo::Slice>',
        'std::vector<std::pair<tomo_db0::Slice, tomo_db0::Slice>'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('unit', choices=('t_hash', 't_hash_ttl'))
    p.add_argument('namespace', choices=('src', 'db0'))
    p.add_argument('values', nargs='+', type=int)
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    out = ROOT / 'build/hexpread-budget' / (a.unit + '-' + a.namespace)
    out.mkdir(parents=True, exist_ok=True)
    rel = ('db0/' if a.namespace == 'db0' else '') + 'src/cmd/' + a.unit + '.o'
    old = inventory(ROOT / 'build/hexpread-pre' / rel)
    for row in old.values():
        row['hot'] = not allowed(row['name'])

    def trial(value):
        target = out / f'{value}.o'
        cmd = ['taskset', '-c', '96-111', 'g++', '-std=c++20', '-O2', '-g', '-Wall',
               '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I.',
               '--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={value}']
        if a.namespace == 'db0':
            cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        cmd += ['-c', f'src/cmd/{a.unit}.cc', '-o', str(target)]
        with target.with_suffix('.log').open('w') as log:
            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        new = inventory(target)
        for row in new.values():
            row['hot'] = not allowed(row['name'])
        result = dict(command=cmd, value=value, **compare(old, new))
        target.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
        print(a.unit, a.namespace, value, 'outside-read', result['hot_changed'],
              'bytes', result['hot_differing_bytes'], flush=True)

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        list(pool.map(trial, a.values))


if __name__ == '__main__':
    main()
