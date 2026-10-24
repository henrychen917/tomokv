#!/usr/bin/env python3
"""Compile-only per-unit budget derivation; every compiler inherits CPUs 48-63."""
import concurrent.futures, hashlib, json, re, shlex, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ccfix4_budget import inventory,compare
PRE=ROOT/'build/datafix1/pre-src'
OUT=ROOT/'docs/datafix1/budgets'
OUT.mkdir(exist_ok=True)

def trial(j):
    obj=j['object']; root=PRE if j.get('pre') else ROOT
    log=ROOT/('docs/datafix1/build-pre.log' if j.get('pre') else 'docs/datafix1/build-randscan.log')
    cmd=next(shlex.split(l) for l in log.read_text().splitlines() if l.startswith('g++ ') and l.endswith(' -o build/'+obj))
    if 'budget' in j:
        i=next(i for i,s in enumerate(cmd) if s.startswith('large-unit-insns=')); cmd[i]='large-unit-insns='+str(j['budget'])
    label=obj.replace('/','_')+('.pre' if j.get('pre') else '.post')+'.'+str(j.get('budget','default'))
    base=ROOT/'build/datafix1/budgets'/label; base.parent.mkdir(exist_ok=True)
    cmd[cmd.index('-o')+1]=str(base)+'.o';cmd+=['-fdump-ipa-inline','-dumpbase',str(base)]
    with Path(str(base)+'.log').open('w') as out:subprocess.run(['taskset','-c','48-63',*cmd],cwd=root,stdout=out,stderr=subprocess.STDOUT,check=True)
    dump=next(base.parent.glob(base.name+'*.inline'))
    with dump.open() as inp:
        unit=next(int(m[1]) for l in inp if (m:=re.search(r'Starting with size (\d+)',l)))
    dump.unlink()
    r=dict(**j,unit=unit,command=cmd,sha256=hashlib.sha256(Path(str(base)+'.o').read_bytes()).hexdigest(),**compare(inventory(PRE/'build'/obj),inventory(Path(str(base)+'.o'))))
    (OUT/(label+'.json')).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k not in ('rows','command')}),flush=True)
    return r

if __name__=='__main__':
    jobs=json.loads(Path(sys.argv[1]).read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:list(pool.map(trial,jobs))
