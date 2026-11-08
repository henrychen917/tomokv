#!/usr/bin/env python3
"""Audit merged PS/CC cold emitter budgets without changing production source."""
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import sys

from ccfix4_budget import BUILD, ROOT, compare, inventory, sha


def selected(path):
    rows = inventory(path)
    for row in rows.values():
        row['hot'] |= bool(re.search(r'::cmd_\w+(?:<|\()', row['name']) and
                           not re.search(r'::cmd_(?:config|info|acl)\(', row['name']))
    return rows


if __name__ == '__main__':
    values = []
    for arg in sys.argv[1:]:
        if ':' in arg:
            low, high = map(int, arg.split(':'))
            values.extend(range(low, high + 1))
        else:
            values.append(int(arg))
    out = ROOT / 'docs/ccfix4/server-budgets'
    build = BUILD / 'server-budgets'
    out.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    pre = BUILD / 'PRE/db0/src/cmd/t_server.o'
    old = selected(pre)
    def trial(value):
        receipt = out / f'{value}.json'
        if receipt.exists():
            return json.loads(receipt.read_text())
        target = build / f'{value}.o'
        command = ['taskset', '-c', '112-127', 'g++', '-std=c++20', '-O2', '-g0',
                   '-Wall', '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
                   '-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0', '-I.',
                   '--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={value}',
                   '-c', 'src/cmd/t_server.cc', '-o', str(target)]
        with (build / f'{value}.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = dict(value=value, pre_sha256=sha(pre), command=command,
                      object_sha256=sha(target), **compare(old, selected(target)))
        receipt.write_text(json.dumps(result, indent=2) + '\n')
        print(value, result['hot_changed'], result['hot_differing_bytes'], flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(trial, dict.fromkeys(values)))
