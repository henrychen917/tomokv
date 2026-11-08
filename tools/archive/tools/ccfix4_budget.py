#!/usr/bin/env python3
"""Reproducible db0/main.o budget search; compile and inspect only, on CPUs 112-127."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from ccfix_audit import audit

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/ccfix4'
OUT = ROOT / 'docs/ccfix4/budgets'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(path):
    elf = audit.Elf(path)
    functions = elf.functions()
    symbols = sorted(functions)
    names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n',
                                    text=True).splitlines()
    return {symbol: dict(name=name, size=functions[symbol]['size'],
                        canonical=elf.canonical(functions[symbol]),
                        hot=bool(audit.HOT.search(name) or
                                 re.search(r'ExLoopT<.*>::run\(', name)))
            for symbol, name in zip(symbols, names)}


def compare(old, new):
    changed = []
    hot = 0
    for symbol in sorted(old.keys() | new.keys()):
        a, b = old.get(symbol), new.get(symbol)
        selected = bool((a and a['hot']) or (b and b['hot']))
        hot += selected
        if a and b and a['canonical'] == b['canonical']:
            continue
        before = a['canonical'][0] if a else b''
        after = b['canonical'][0] if b else b''
        changed.append(dict(symbol=symbol, name=(a or b)['name'], hot=selected,
                            pre_size=a['size'] if a else 0,
                            post_size=b['size'] if b else 0,
                            differing_bytes=sum(x != y for x, y in zip(before, after)) +
                                            abs(len(before) - len(after)),
                            targets_equal=bool(a and b and
                                               a['canonical'][1] == b['canonical'][1])))
    selected = [r for r in changed if r['hot']]
    return dict(total=len(old.keys() | new.keys()), hot=hot,
                changed=len(changed), hot_changed=len(selected),
                hot_differing_bytes=sum(r['differing_bytes'] for r in selected), rows=changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('values', nargs='+', help='none, integer, or inclusive LOW:HIGH range')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args()
    values = []
    for value in args.values:
        if ':' in value:
            low, high = map(int, value.split(':'))
            values.extend(range(low, high + 1))
        else:
            values.append(None if value == 'none' else int(value))
    values = list(dict.fromkeys(values))
    OUT.mkdir(parents=True, exist_ok=True)
    trials = BUILD / 'budgets'
    trials.mkdir(parents=True, exist_ok=True)
    pre = BUILD / 'PRE/db0/src/main.o'
    old = inventory(pre)
    pre_sha = sha(pre)
    source_tree = subprocess.check_output(['git', 'rev-parse', 'HEAD:src'],
                                         cwd=ROOT, text=True).strip()
    # -g0 saves only debug generation. Its full function inventory is separately
    # compared with the release -g object at the same 146270 budget before use.
    flags = ['taskset', '-c', '112-127', 'g++', '-std=c++20', '-O2', '-g0',
             '-Wall', '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
             '-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0', '-I.']

    def trial(value):
        label = str(value) if value is not None else 'none'
        target = trials / (label + '.o')
        receipt = OUT / (label + '.json')
        command = flags.copy()
        if value is not None:
            command += ['--param', 'inline-unit-growth=0', '--param',
                        f'large-unit-insns={value}']
        command += ['-c', 'src/main.cc', '-o', str(target)]
        identity = dict(value=value, pre_sha256=pre_sha, source_tree=source_tree,
                        command=command)
        if receipt.exists():
            result = json.loads(receipt.read_text())
            assert all(result[k] == v for k, v in identity.items()), 'stale search receipt'
            return result
        start = time.monotonic()
        with (trials / (label + '.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True)
        result = dict(**identity, seconds=time.monotonic() - start,
                      object_sha256=sha(target), **compare(old, inventory(target)))
        receipt.write_text(json.dumps(result, indent=2) + '\n')
        print(label, 'hot', result['hot'] - result['hot_changed'], '/', result['hot'],
              'changed', result['changed'], 'seconds', round(result['seconds'], 1), flush=True)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(trial, values))
    results = [json.loads(p.read_text()) for p in OUT.glob('*.json')]
    results.sort(key=lambda r: (-1 if r['value'] is None else r['value']))
    (OUT.parent / 'budget-search.json').write_text(json.dumps([
        {k: v for k, v in r.items() if k not in ('rows', 'command')}
        for r in results], indent=2) + '\n')
    numeric = [r for r in results if r['value'] is not None]
    best = min(numeric, key=lambda r: (r['hot_changed'], r['hot_differing_bytes'], r['value']))
    print('BEST', best['value'], 'hot_changed', best['hot_changed'],
          'hot_differing_bytes', best['hot_differing_bytes'], flush=True)


if __name__ == '__main__':
    main()
