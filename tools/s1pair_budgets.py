#!/usr/bin/env python3
"""Compile-only inline-budget trials for the two units s1pair changes; never starts a server.

PRE is the base commit's source compiled with the base Makefile's own command; each trial
compiles the working tree's source with one candidate large-unit-insns value. Both use -g0
(debug generation only). Every function body is compared (tools/archive/tools/ccfix4_budget),
and changed bodies whose names are not scripting or config functions are listed as
"outside". A candidate is usable only with no outside body; the linked binary is then
compared with the release by tools/s1pair_identity.py.

  tools/s1pair_budgets.py --cores 48-55 --unit db0/src/cmd/t_server.o 34300:34500
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/archive/tools'))
from ccfix4_budget import compare, inventory  # noqa: E402

UNITS = ('src/cmd/scripting.o', 'db0/src/cmd/scripting.o',
         'src/cmd/t_server.o', 'db0/src/cmd/t_server.o')
ALLOWED = re.compile(r'config|Config|cfg_|script|Script|eval|Eval|lua|Lua|redis_|open_helper|'
                     r'validate_source')


def command(makefile, unit):
    lines = subprocess.check_output(['make', '-f', str(makefile), '-Bn', 'build/' + unit],
                                    cwd=ROOT, text=True).splitlines()
    cmd, = [shlex.split(line) for line in lines
            if line.startswith('g++ ') and line.endswith(' -o build/' + unit)]
    return ['-g0' if x == '-g' else x for x in cmd]


def with_budget(cmd, budget):
    return [f'large-unit-insns={budget}' if x.startswith('large-unit-insns=') else x for x in cmd]


def compile_unit(cmd, source, obj, cores):
    cmd = list(cmd)
    cmd[cmd.index('-o') + 1] = str(obj)
    if source:
        cmd[cmd.index(next(x for x in cmd if x.endswith('.cc')))] = str(source)
        cmd += ['-Isrc/cmd']
    dump = obj.with_suffix('.inline')
    cmd += ['-fdump-ipa-inline=' + str(dump)]
    with obj.with_suffix('.log').open('w') as log:
        subprocess.run(['taskset', '-c', cores, *cmd], cwd=ROOT, check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    initial = int(re.search(r'Starting with size (\d+)', dump.read_text())[1])
    dump.unlink()
    return cmd, initial


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cores', required=True)
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--base', default='7595a6705a')
    p.add_argument('--unit', action='append', choices=UNITS)
    p.add_argument('--out', type=Path, default=ROOT / 'build/s1pair/budgets')
    p.add_argument('values', nargs='*', help='integer or inclusive LOW:HIGH[:STEP]; '
                   'none = the current Makefile value')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    base_makefile = a.out / 'Makefile.base'
    base_makefile.write_bytes(subprocess.check_output(['git', 'show', a.base + ':Makefile'],
                                                      cwd=ROOT))
    values = []
    for value in a.values or ['none']:
        if value == 'none':
            values.append(None)
            continue
        low, _, rest = value.partition(':')
        high, _, step = rest.partition(':')
        values.extend(range(int(low), int(high or low) + 1, int(step or 1)))
    units = a.unit or list(UNITS)

    def pre(unit):
        source = unit.removeprefix('db0/').removesuffix('.o') + '.cc'
        copy = a.out / (unit.replace('/', '_') + '-PRE.cc')
        copy.write_bytes(subprocess.check_output(['git', 'show', f'{a.base}:{source}'], cwd=ROOT))
        obj = a.out / (unit.replace('/', '_') + '-PRE.o')
        cmd, initial = compile_unit(command(base_makefile, unit), copy, obj, a.cores)
        return unit, dict(object=obj, initial=initial, inventory=inventory(obj), command=cmd)

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        reference = dict(pool.map(pre, units))

    def trial(task):
        unit, budget = task
        cmd = command(Path('Makefile'), unit)
        current = int(next(x.split('=')[1] for x in cmd if x.startswith('large-unit-insns=')))
        budget = current if budget is None else budget
        label = f"{unit.replace('/', '_')}-POST-{budget}"
        obj = a.out / (label + '.o')
        cmd, initial = compile_unit(with_budget(cmd, budget), None, obj, a.cores)
        ref = reference[unit]
        result = dict(unit=unit, budget=budget, makefile_budget=current, initial=initial,
                      pre_initial=ref['initial'], command=cmd, pre_command=ref['command'],
                      **compare(ref['inventory'], inventory(obj)))
        result['outside'] = [r['name'] for r in result['rows'] if not ALLOWED.search(r['name'])]
        (a.out / (label + '.json')).write_text(json.dumps(result, indent=2) + '\n')
        obj.unlink()
        print(label, 'initial', initial, 'pre_initial', ref['initial'], 'changed',
              result['changed'], 'outside', len(result['outside']), result['outside'][:6],
              flush=True)
        return result

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        list(pool.map(trial, [(u, v) for u in units for v in values]))


if __name__ == '__main__':
    main()
