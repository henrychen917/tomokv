#!/usr/bin/env python3
"""Compile-only IPA surveys and trials; every child inherits CPUs 0-15."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

import ccfix_audit  # installs relocation canonicalisation
from lbstall_artifacts import Elf, HOT

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flushfix2/budgets'
OUT = ROOT / 'docs/flushfix2/budgets'
PRE = ROOT / 'build/flushfix2/pre'
SELECT = re.compile(HOT.pattern + r'|::cmd_\w+(?:<|\()|xshard_(?:prepare|execute|task_should_defer)\(|atomic_visit_key_groups|multi_cancel_record')


def recipes():
    listing = subprocess.check_output(['make', '-n', '-W', 'Makefile', 'all'],
                                      cwd=ROOT, text=True).replace('\\\n', ' ')
    result = {}
    for line in listing.splitlines():
        if line.startswith('g++ '):
            cmd = shlex.split(line)
            if '-c' in cmd:
                result[cmd[cmd.index('-o') + 1].removeprefix('build/')] = cmd
    return result


def trial(item):
    unit, value, commands, revision, keep = item
    label = unit.replace('/', '_') + '-' + str(value)
    receipt = OUT / (label + '.json')
    if receipt.exists():
        row = json.loads(receipt.read_text())
        if row.get('revision') == revision and (not keep or Path(row['object']).exists()):
            return row
    output = BUILD / (label + '.o')
    dump = BUILD / (label + '.inline')
    cmd = commands[unit].copy()
    old_budget = next((int(x.split('=')[1]) for x in cmd if x.startswith('large-unit-insns=')), 10000)
    budget, _, auto = str(value).partition(':')
    if budget not in ('current', 'pre'):
        cmd += ['--param', f'large-unit-insns={budget}']
    if auto:
        cmd += ['--param', f'max-inline-insns-auto={int(auto)}']
    cmd[cmd.index('-o') + 1] = str(output)
    cmd = ['taskset', '-c', '0-15', *cmd, '-g0', f'-fdump-ipa-inline={dump}']
    cwd = ROOT / 'build/flushfix2/pre-source' if value == 'pre' else ROOT
    with (BUILD / (label + '.log')).open('w') as log:
        subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)
    initial = int(re.search(r'Starting with size (\d+)', dump.read_text())[1])
    dump.unlink()
    a, b = Elf(PRE / unit), Elf(output)
    old, new = a.functions(), b.functions()
    names = sorted(old)
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    changed, total = [], 0
    for symbol, name in zip(names, labels):
        if SELECT.search(name):
            total += 1
            if symbol not in new or a.canonical(old[symbol]) != b.canonical(new[symbol]):
                changed.append(name)
    if not keep:
        output.unlink()
    row = dict(unit=unit, budget=value, old_budget=old_budget, initial=initial,
               changed=changed, total=total, command=cmd, revision=revision, object=str(output))
    receipt.write_text(json.dumps(row, indent=2) + '\n')
    print(unit, value, initial, len(changed), flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--units', default='changed')
    p.add_argument('--values', default='pre,current')
    p.add_argument('--derive', action='store_true')
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--keep-objects', action='store_true')
    args = p.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    commands = recipes()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    revision += ':' + hashlib.sha256(subprocess.check_output(
        ['git', 'diff', 'HEAD', '--', 'src', 'Makefile', 'tools/flushfix2_budget.py'], cwd=ROOT)).hexdigest()
    if args.units == 'changed':
        changed = json.loads((ROOT / 'docs/flushfix2/identity-cold/changed-bodies.json').read_text())
        units = sorted({r['object'] for r in changed})
    else:
        units = args.units.split(',')
    work = []
    for unit in units:
        values = args.values.split(',')
        if args.derive:
            stem = unit.replace('/', '_')
            a = json.loads((OUT / (stem + '-pre.json')).read_text())
            b = json.loads((OUT / (stem + '-current.json')).read_text())
            centre = a['old_budget'] + b['initial'] - a['initial']
            values = [str(centre + offset) for offset in (-2, 0, 2)]
        work += [(unit, v, commands, revision, args.keep_objects) for v in values]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(trial, work))
    print('Trials', len(rows), flush=True)


if __name__ == '__main__':
    main()
