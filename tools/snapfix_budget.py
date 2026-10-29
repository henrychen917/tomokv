#!/usr/bin/env python3
"""Compile-only inline-budget survey/trials for the snapfix units; no workload, no rates.

Adapted from tools/execindex_budget.py. For each hot unit it records GCC's initial IPA unit size
("Starting with size N") and compares every HOT body (tools/lbstall_artifacts.HOT plus the
xshard prepare/execute entry points) of the trial object with PRE's object, masking relocations.

  --survey               PRE and POST at their Makefile budgets
  --unit U v1 v2 ...     POST trials of unit U at budgets v1, v2, ...
  --refresh              re-compare kept trial objects (build/snapfix/budgets) without compiling

A body that differs from PRE only in its alignment NOP encoding is reported under 'padding', not
'changed'. tools/snapfix_budget_bodies.py scores the same kept objects on every function body.

The snapshot drain's two ThreadCtx instantiations are RENAMED by the fix (drain_tasks ->
drain_tasks_capped, drain_tasks_unmasked -> drain_tasks_unmasked_capped, same lambda): PRE symbols
and call targets are mapped through rename() before comparing, so a caller whose only difference
is that call target compares equal, and the renamed bodies themselves are reported as changed.
"""
import argparse
import concurrent.futures
import json
import re
import shlex
import subprocess
from pathlib import Path

from lbstall_artifacts import Elf, HOT
import snapfix_identity

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/snapfix/budgets'
BUILD = ROOT / 'build/snapfix/budgets'
OUT.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)
UNITS = [prefix + suffix for prefix in ['src/', 'db0/src/']
         for suffix in ['cmd/xshard.o', 'main.o', 'core/genthread.o', 'core/rl2s.o', 'core/reorder.o']]
PRE_SOURCE = ROOT / 'build/snapfix/pre-source'
PRE_OBJECTS = ROOT / 'build/snapfix/pre'
CPUS = '16-31'
REFRESH = False   # --refresh: recompare kept trial objects without recompiling


def recipes(source, build):
    text = subprocess.check_output(['make', '-n', '-W', 'Makefile', 'BUILD_ROOT=' + str(build), 'all'],
                                   cwd=source, text=True).replace('\\\n', ' ')
    result = {}
    for line in text.splitlines():
        if line.startswith('g++ '):
            cmd = shlex.split(line)
            if '-c' in cmd:
                result[str(Path(cmd[cmd.index('-o') + 1]).relative_to(build))] = cmd
    return result


COMMANDS = {'pre': recipes(PRE_SOURCE, PRE_OBJECTS), 'post': recipes(ROOT, ROOT / 'build')}


RENAMES = [
    (re.compile(r'^(_ZN\w*?9ThreadCtx)11drain_tasksILb([01])E(RZN.*?drain_tasks_snapshotILj(\d+)E.*)OT0_$'),
     lambda m: f'{m[1]}18drain_tasks_cappedILb{m[2]}ELj{m[4]}E{m[3]}OT1_'),
    (re.compile(r'^(_ZN\w*?9ThreadCtx)20drain_tasks_unmaskedILb([01])E(RZN.*?drain_tasks_snapshotILj(\d+)E.*)OT0_$'),
     lambda m: f'{m[1]}27drain_tasks_unmasked_cappedILb{m[2]}ELj{m[4]}E{m[3]}OT1_'),
]


def rename(name):
    for rx, rep in RENAMES:
        if rx.match(name):
            return rx.sub(rep, name)
    return name


TEXT = {}


def text_bodies(path, pre, padding):
    # snapfix_identity's normalized disassembly: an assembler-resolved RIP displacement to a local
    # code symbol (e.g. a destructor registered with __cxa_thread_atexit) moves with unrelated code
    # in the section, which Elf.canonical() reads as a changed byte; the text form compares the
    # named target instead. padding=False also ignores the alignment NOP encoding.
    key = (str(path), pre, padding)
    if key not in TEXT:
        TEXT[key] = snapfix_identity.bodies(path, pre, padding)
    return TEXT[key]


def compare(old_elf, old_symbol, new_elf, new_symbol, renamed=True):
    """'equal', 'padding' (only the alignment NOP encoding differs) or 'changed'.

    renamed=False (the PRE arm's own recompiles) compares names as they are."""
    a, b = old_elf.canonical(old_symbol), new_elf.canonical(new_symbol)
    ren = rename if renamed else (lambda x: x)
    norm = lambda t: t if not isinstance(t, tuple) else (ren(t[0]) if isinstance(t[0], str) else t[0], *t[1:])
    if a[0] == b[0] and [(o, k, norm(t)) for o, k, t in a[1]] == [(o, k, t) for o, k, t in b[1]]:
        return 'equal'
    name = snapfix_identity.canon(new_symbol['name'])
    for padding, verdict in ((True, 'equal'), (False, 'padding')):
        old_text = text_bodies(old_elf.path, renamed, padding).get(name)
        if old_text is not None and old_text == text_bodies(new_elf.path, False, padding).get(name):
            return verdict
    return 'changed'


def same(old_elf, old_symbol, new_elf, new_symbol):
    return compare(old_elf, old_symbol, new_elf, new_symbol) == 'equal'


def hot_names(elf):
    names = list(elf.functions())
    readable = subprocess.check_output(['c++filt'], input='\n'.join(names), text=True).splitlines()
    return {s: r for s, r in zip(names, readable)
            if HOT.search(r) or re.search(r'xshard_(prepare|execute)\(', r)}


def run(item):
    arm, unit, value = item
    label = arm + '-' + unit.replace('/', '_') + '-' + str(value)
    receipt = OUT / (label + '.json')
    output = BUILD / (label + '.o')
    if receipt.exists() and not REFRESH:
        return json.loads(receipt.read_text())
    dump = BUILD / (label + '.inline')
    cmd = COMMANDS[arm][unit].copy()
    budget = int(next(x.split('=')[1] for x in cmd if x.startswith('large-unit-insns=')))
    if value is not None:
        cmd = [f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x for x in cmd]
    cmd[cmd.index('-o') + 1] = str(output)
    cmd = ['taskset', '-c', CPUS, *cmd, '-g0', f'-fdump-ipa-inline={dump}']
    if receipt.exists() and output.exists():
        previous = json.loads(receipt.read_text())
        initial, final = previous['initial'], []
    else:
        with (BUILD / (label + '.log')).open('w') as log:
            subprocess.run(cmd, cwd=PRE_SOURCE if arm == 'pre' else ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        text = dump.read_text()
        initial = int(re.search(r'Starting with size (\d+)', text)[1])
        final = re.findall(r'Unit growth for small function inlining: (\d+)->(\d+)', text)
        dump.unlink()
    old_elf, new_elf = Elf(PRE_OBJECTS / unit), Elf(output)
    old, new = old_elf.functions(), new_elf.functions()
    changed, missing, padding = [], [], []
    hot = hot_names(old_elf)
    renamed = arm == 'post'
    for symbol, name in hot.items():
        target = rename(symbol) if renamed else symbol
        if target not in new:
            missing.append(name)
            continue
        verdict = 'changed' if target != symbol else compare(old_elf, old[symbol], new_elf, new[target], renamed)
        if verdict == 'changed':
            changed.append(name)
        elif verdict == 'padding':
            padding.append(name)
    fresh = sorted(new.keys() - {rename(x) if renamed else x for x in old.keys()})
    added = subprocess.check_output(['c++filt'], input='\n'.join(fresh), text=True).splitlines() if fresh else []
    row = dict(arm=arm, unit=unit, budget=budget if value is None else value, initial=initial,
               growth=final[-1] if final else None, command=cmd, hot=len(hot), changed=changed,
               padding=padding, missing=missing, added=added)
    receipt.write_text(json.dumps(row, indent=2) + '\n')
    print(label, initial, 'hot', len(hot), 'changed', len(changed), 'missing', len(missing), flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--survey', action='store_true')
    p.add_argument('--unit')
    p.add_argument('--refresh', action='store_true')
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('values', nargs='*', type=int)
    a = p.parse_args()
    global REFRESH
    REFRESH = a.refresh
    jobs = ([(arm, unit, None) for arm in ['pre', 'post'] for unit in UNITS] if a.survey
            else [('post', a.unit, v) for v in a.values])
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(run, jobs))
    name = 'survey.json' if a.survey else a.unit.replace('/', '_') + '-trials.json'
    (OUT / name).write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
