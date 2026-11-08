#!/usr/bin/env python3
"""Compile only a changed TU and reject every unrelated emitted-body difference."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
from ccfix4_budget import inventory, compare

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tu', choices=('stream', 'list'))
p.add_argument('variant', choices=('src', 'db0'))
p.add_argument('values', nargs='+', type=int)
p.add_argument('--jobs', type=int, default=3)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
relative = Path('db0/src/cmd' if a.variant == 'db0' else 'src/cmd') / f't_{a.tu}.o'
old = inventory(root / 'build/aclkeys4/BASE' / relative)
allowed = re.compile(r'::(?:cmd_xadd<|xshard_push_list_element_impl<)')
for row in old.values(): row['hot'] = not bool(allowed.search(row['name']))
command = next(line.split() for line in (root/'build/aclkeys4/merged-build.log').read_text().splitlines()
               if line.startswith('g++ ') and line.endswith(' -o build/'+str(relative)))
command = ['-g0' if x == '-g' else x for x in command]
folder = root / 'build/aclkeys4/budgets' / f'{a.tu}-{a.variant}'
folder.mkdir(parents=True, exist_ok=True)
def trial(value):
    output = folder / f'{value}.o'
    cmd = command.copy()
    cmd[cmd.index('-o')+1] = str(output)
    cmd += ['--param', 'inline-unit-growth=0', '--param', f'large-unit-insns={value}']
    with (folder/f'{value}.log').open('w') as log:
        subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    new = inventory(output)
    for row in new.values(): row['hot'] = not bool(allowed.search(row['name']))
    result = dict(value=value, command=cmd, **compare(old,new))
    (folder/f'{value}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','command')}),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
    list(pool.map(trial,a.values))
