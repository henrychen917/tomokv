#!/usr/bin/env python3
"""Second budget criterion: ALL function bodies (not only HOT) of kept compile-only trial objects.

For every kept trial object build/snapfix/budgets/post-<unit>-<value>.o, compare every function
with PRE's object using snapfix_identity's normalized disassembly (PRE names mapped through the
fix's renames). Intended bodies (the snapshot drains, the script Final close, the post-join
teardown and its new functions) are listed separately. Writes docs/snapfix/budgets/bodies.json.
No server, no rates.
"""
import concurrent.futures
import json
import re
import subprocess
from pathlib import Path

import snapfix_identity as I

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/snapfix/budgets'
PRE = ROOT / 'build/snapfix/pre'
OUT = ROOT / 'docs/snapfix/budgets/bodies.json'
INTENDED = re.compile(r'drain_tasks_snapshot|drain_tasks(_unmasked)?_capped|script_snapshot_done|'
                      r'shutdown_release_abandoned_script_pins|atomic_release_abandoned_script_pins|'
                      r'run_fused_server|run_split_read_local_server|run_fused_server_reordered|main::\{lambda\(\)#1\}')


def demangle(names):
    return subprocess.check_output(['c++filt'], input='\n'.join(names), text=True).splitlines() if names else []


def unit_of(path):
    m = re.match(r'post-(.+)-(None|\d+)\.o$', path.name)
    return m[1].replace('_', '/', m[1].count('_')).replace('db0/src', 'db0/src'), m[2]


def compare(item):
    unit, value, path = item
    old_s, new_s = I.bodies(PRE / unit, True), I.bodies(path)
    old_p, new_p = I.bodies(PRE / unit, True, False), I.bodies(path, False, False)
    differ = sorted(n for n in old_s.keys() & new_s.keys() if old_s[n] != new_s[n])
    changed = [n for n in differ if old_p[n] != new_p[n]]
    padding = [n for n in differ if old_p[n] == new_p[n]]
    names = dict(zip(changed, demangle(changed)))
    intended = [names[n] for n in changed if INTENDED.search(names[n])]
    other = [names[n] for n in changed if not INTENDED.search(names[n])]
    return dict(unit=unit, budget=value, intended=len(intended), other=other, padding=len(padding),
                added=len(new_s.keys() - old_s.keys()), removed=len(old_s.keys() - new_s.keys()))


def main():
    units = {'src/cmd/xshard.o': 'src_cmd_xshard.o', 'db0/src/cmd/xshard.o': 'db0_src_cmd_xshard.o',
             'src/core/rl2s.o': 'src_core_rl2s.o', 'src/core/reorder.o': 'src_core_reorder.o',
             'db0/src/core/genthread.o': 'db0_src_core_genthread.o', 'src/main.o': 'src_main.o',
             'db0/src/main.o': 'db0_src_main.o', 'src/core/genthread.o': 'src_core_genthread.o',
             'db0/src/core/rl2s.o': 'db0_src_core_rl2s.o', 'db0/src/core/reorder.o': 'db0_src_core_reorder.o'}
    items = []
    for unit, stem in units.items():
        for path in sorted(BUILD.glob(f'post-{stem}-*.o')):
            value = path.name[len(f'post-{stem}-'):-2]
            items.append((unit, value, path))
    with concurrent.futures.ThreadPoolExecutor(14) as pool:
        rows = list(pool.map(compare, items))
    OUT.write_text(json.dumps(rows, indent=1) + '\n')
    for row in sorted(rows, key=lambda r: (r['unit'], r['budget'] != 'None', int(r['budget']) if r['budget'] != 'None' else 0)):
        print(row['unit'], row['budget'], 'other', len(row['other']), 'padding', row['padding'], 'intended', row['intended'])


if __name__ == '__main__':
    main()
