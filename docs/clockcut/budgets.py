#!/usr/bin/env python3
"""Compile-only per-unit clockcut inlining trials, inheriting CPUs 64-79."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ccfix4_budget import inventory, compare
OUT = ROOT / 'build/clockcut/budgets'
PRE = ROOT / 'build/clockcut/pre-source'
# The eight IO units whose IPA size the refresh changed (the initial identity inventory's objects).
OBJECTS = sorted({r['object'] for r in json.loads((ROOT / 'docs/clockcut/budget-units.json').read_text())})

def trial(job):
    obj, arm, increment = job
    command = next(shlex.split(s) for s in (ROOT/'build/clockcut/pre-build.log').read_text().splitlines()
                   if s.startswith('g++ ') and s.endswith(' -o build/clockcut/pre/' + obj))
    before_budget = next(int(s.split('=')[1]) for s in command if s.startswith('large-unit-insns='))
    if increment:
        command = [f'large-unit-insns={before_budget+increment}' if s.startswith('large-unit-insns=') else s for s in command]
    base = OUT / (obj.replace('/', '_') + f'.{arm}.{increment}')
    receipt = base.with_suffix(base.suffix + '.json')
    if receipt.exists(): return json.loads(receipt.read_text())
    output = str(base)+'.o'
    command[command.index('-o')+1] = output
    command += ['-fdump-ipa-inline', '-dumpbase', str(base)]
    with open(str(base)+'.log','w') as log:
        subprocess.run(command,cwd=PRE if arm=='pre' else ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    dump = next(OUT.glob(base.name+'*.inline'))
    with dump.open() as f:
        unit = next(int(m[1]) for s in f if (m:=re.search(r'Starting with size (\d+)',s)))
    dump.unlink()
    result = dict(object=obj,arm=arm,increment=increment,budget=before_budget+increment,unit=unit,
                  command=command,output=output,sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest())
    if arm=='post':
        result.update(compare(inventory(ROOT/'build/clockcut/pre'/obj),inventory(Path(output))))
        result['spillover']=[r for r in result['rows'] if 'ExLoopT<' not in r['name']]
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(obj,arm,increment,'unit',unit,'changed',result.get('changed'),
          'spillover',len(result.get('spillover',[])),flush=True)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    phase=sys.argv[1]
    if phase=='units': jobs=[(obj,arm,0) for obj in OBJECTS for arm in ('pre','post')]
    else:
        units=json.loads((ROOT/'docs/clockcut/budget-units.json').read_text())
        jobs=[]
        for obj in OBJECTS:
            old=next(r for r in units if r['object']==obj and r['arm']=='pre')
            new=next(r for r in units if r['object']==obj and r['arm']=='post')
            if phase=='scan' and not new['spillover']: continue
            delta=new['unit']-old['unit']
            for adjustment in [int(s) for s in sys.argv[2:]] or [0]: jobs.append((obj,'post',delta+adjustment))
    with ProcessPoolExecutor(max_workers=16) as pool: rows=list(pool.map(trial,jobs))
    (ROOT/f'docs/clockcut/budget-{phase}.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__': main()
