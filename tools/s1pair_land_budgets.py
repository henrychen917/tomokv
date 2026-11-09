#!/usr/bin/env python3
"""Compile-only paper-build budget proof; no servers or measurements.

Inventory every pinned Makefile row using preprocessed source and compiler flags.
Survey the changed units plus xshard with GCC's initial IPA size and the same
complete-body comparator used by s1pair. Optional values scan one unit.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/archive/tools'))
from ccfix4_budget import compare, inventory


def commands(root):
    lines = subprocess.check_output(['make', '-Bn', 'all'], cwd=root, text=True).splitlines()
    result = {}
    for line in lines:
        cmd = shlex.split(line)
        if cmd and cmd[0] == 'g++' and '-c' in cmd and any(
                x.startswith('large-unit-insns=') for x in cmd):
            unit = cmd[cmd.index('-o') + 1].removeprefix('build/')
            result[unit] = ['-g0' if x == '-g' else x for x in cmd]
    return result


def budget(cmd):
    return int(next(x.split('=')[1] for x in cmd if x.startswith('large-unit-insns=')))


def run(cmd, root, cores, log):
    with log.open('w') as stream:
        subprocess.run(['taskset', '-c', cores, *cmd], cwd=root, check=True,
                       stdout=stream, stderr=subprocess.STDOUT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre-tree', type=Path, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--unit')
    parser.add_argument('values', nargs='*', type=int)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    before, after = commands(args.pre_tree), commands(ROOT)
    assert before.keys() == after.keys(), 'pinned unit inventory changed'

    def preprocess(task):
        unit, root, command, arm = task
        output = args.out / (unit.replace('/', '_') + '-' + arm + '.ii')
        cmd = command.copy()
        cmd[cmd.index('-c')] = '-E'
        cmd[cmd.index('-o') + 1] = str(output)
        cmd.append('-P')
        run(cmd, root, args.cores, output.with_suffix('.preprocess.log'))
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        output.unlink()
        return (unit, arm), digest

    if not args.unit:
        tasks = [(u, root, cmds[u], arm) for u in before
                 for root, cmds, arm in ((args.pre_tree, before, 'PRE'), (ROOT, after, 'POST'))]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            hashes = dict(pool.map(preprocess, tasks))
        rows = []
        for unit in before:
            flags_equal = [x for x in before[unit] if not x.startswith('large-unit-insns=')] == [
                x for x in after[unit] if not x.startswith('large-unit-insns=')]
            rows.append(dict(unit=unit, pre_budget=budget(before[unit]),
                             post_budget=budget(after[unit]), flags_equal=flags_equal,
                             preprocessed_equal=hashes[unit, 'PRE'] == hashes[unit, 'POST'],
                             pre_sha256=hashes[unit, 'PRE'], post_sha256=hashes[unit, 'POST']))
        (args.out / 'inventory.json').write_text(json.dumps(rows, indent=2) + '\n')
        changed = [r['unit'] for r in rows if not r['preprocessed_equal'] or not r['flags_equal']]
        print('Pinned rows:', len(rows), 'changed inputs:', changed, flush=True)
        assert set(changed) == {p + 'src/cmd/' + f + '.o' for p in ('', 'db0/')
                               for f in ('scripting', 't_server')}
        units = changed + ['src/cmd/xshard.o', 'db0/src/cmd/xshard.o']
    else:
        units = [args.unit]

    def compile_object(unit, root, command, arm, cap):
        obj = args.out / (unit.replace('/', '_') + '-' + arm + '-' + str(cap) + '.o')
        cmd = [f'large-unit-insns={cap}' if x.startswith('large-unit-insns=') else x
               for x in command]
        cmd[cmd.index('-o') + 1] = str(obj)
        dump = obj.with_suffix('.inline')
        cmd.append('-fdump-ipa-inline=' + str(dump))
        run(cmd, root, args.cores, obj.with_suffix('.log'))
        initial = int(re.search(r'Starting with size (\d+)', dump.read_text())[1])
        dump.unlink()
        return dict(initial=initial, object=str(obj), command=cmd, inventory=inventory(obj))

    def reference(unit):
        return unit, compile_object(unit, args.pre_tree, before[unit], 'PRE', budget(before[unit]))

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        references = dict(pool.map(reference, units))

    def trial(task):
        unit, cap = task
        pre = references[unit]
        post = compile_object(unit, ROOT, after[unit], 'POST', cap)
        result = dict(unit=unit, pre_budget=budget(before[unit]), post_budget=cap,
                      pre_initial=pre['initial'], post_initial=post['initial'],
                      pre_command=pre['command'], post_command=post['command'],
                      **compare(pre['inventory'], post['inventory']))
        result['outside'] = [r['name'] for r in result['rows'] if not re.search(
            r'config|Config|cfg_|script|Script|eval|Eval|lua|Lua|redis_|open_helper|validate_source',
            r['name'])]
        filename = unit.replace('/', '_') + '-' + str(cap) + '.json'
        (args.out / filename).write_text(json.dumps(result, indent=2) + '\n')
        print(unit, cap, 'initial', pre['initial'], '->', post['initial'],
              'changed', result['changed'], 'outside', result['outside'], flush=True)
        Path(post['object']).unlink()

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(trial, [(u, v) for u in units for v in args.values or [budget(after[u])]]))


if __name__ == '__main__':
    main()
