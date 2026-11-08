#!/usr/bin/env python3
"""AT4.12 compile-only per-unit IPA budget trials (no server, no workload, no rates).

The lane changes the size of five translation units per namespace (xshard.o grows with the
escalation code; the IO-template units shrink with the cold resume arm). With
--param inline-unit-growth=0 the per-unit --param large-unit-insns budget then shifts GCC's
inlining decisions in UNCHANGED code. Each trial recompiles one POST unit with a candidate budget
(-g0, -fdump-ipa-inline) and compares every hot body (lbstall_artifacts.HOT), every command
handler and xshard_prepare/xshard_execute against the PRE object, with relocation-canonical
bodies (tools/ccfix_audit.py canonicalisation). Receipts: docs/at412/budgets2/.

usage: at412_budget.py UNIT VALUE... | --survey
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ccfix_audit  # noqa: E402,F401  (installs the canonical-body extensions)
from lbstall_artifacts import Elf, HOT  # noqa: E402

PRE = ROOT / 'build/at412/pre'
OUT = ROOT / 'docs/at412/budgets2'
BUILD = ROOT / 'build/at412/budgets2'
SELECT = re.compile(HOT.pattern + r'|::cmd_\w+(?:<|\()|xshard_(?:prepare|execute)\(')


def recipes():
    text = subprocess.check_output(['make', '-n', '-W', 'Makefile', 'all'], cwd=ROOT,
                                   text=True).replace('\\\n', ' ')
    result = {}
    for line in text.splitlines():
        if line.startswith('g++ '):
            cmd = shlex.split(line)
            if '-c' in cmd:
                result[cmd[cmd.index('-o') + 1].removeprefix('build/')] = cmd
    return result


def trial(item):
    unit, value, commands = item
    label = unit.replace('/', '_') + '-' + str(value)
    receipt = OUT / (label + '.json')
    if receipt.exists():
        return json.loads(receipt.read_text())
    output = BUILD / (label + '.o')
    dump = BUILD / (label + '.inline')
    cmd = commands[unit].copy()
    if value != 'current':
        cmd = [f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x for x in cmd]
    cmd[cmd.index('-o') + 1] = str(output)
    cmd = ['taskset', '-c', '48-63', *cmd, '-g0', f'-fdump-ipa-inline={dump}']
    with (BUILD / (label + '.log')).open('w') as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    initial = int(re.search(r'Starting with size (\d+)', dump.read_text())[1])
    dump.unlink()
    a, b = Elf(PRE / unit), Elf(output)
    old, new = a.functions(), b.functions()
    names = sorted(old)
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    changed, total = [], 0
    for symbol, name in zip(names, labels):
        if not SELECT.search(name):
            continue
        total += 1
        if symbol not in new or a.canonical(old[symbol]) != b.canonical(new[symbol]):
            changed.append(name)
    output.unlink()
    row = dict(unit=unit, budget=value, initial=initial, changed=changed, total=total,
               command=cmd)
    receipt.write_text(json.dumps(row, indent=2) + '\n')
    print(unit, value, initial, len(changed), flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('unit')
    p.add_argument('values', nargs='+')
    p.add_argument('--jobs', type=int, default=16)
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    commands = recipes()
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(trial, [(a.unit, v, commands) for v in a.values]))
    best = min(rows, key=lambda r: (len(r['changed']), abs(int(r['budget']) if r['budget'] != 'current' else 0)))
    print('BEST', a.unit, best['budget'], len(best['changed']), flush=True)


if __name__ == '__main__':
    main()
