#!/usr/bin/env python3
"""Compile-only merged IPA trials, judged against the supplied linked references."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

import identity
ROOT = identity.ROOT
OUT = ROOT/'build/wave4/budgets'
DOC = ROOT/'docs/wave4/budgets'
sys.path.insert(0, str(ROOT/'tools'))
from ccfix_audit import audit


def code_digest(path):
    elf = audit.Elf(path)
    return hashlib.sha256(repr([(s, elf.canonical(f)) for s,f in sorted(elf.functions().items())]).encode()).hexdigest()


def trial(job):
    obj, budget = job['object'], job['budget']
    base = OUT/(obj.replace('/','_')+'.'+str(budget))
    receipt = base.with_suffix(base.suffix+'.json')
    if receipt.exists(): return json.loads(receipt.read_text())
    command = next(shlex.split(s) for s in (ROOT/'build/wave4/build-rebuilt.log').read_text().splitlines()
                   if s.startswith('g++ ') and s.endswith(' -o build/'+obj))
    command = [f'large-unit-insns={budget}' if s.startswith('large-unit-insns=') else s for s in command]
    output = str(base)+'.o'
    command[command.index('-o')+1] = output
    command += ['-fdump-ipa-inline', '-dumpbase', str(base)]
    with open(str(base)+'.log','w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    dump, = OUT.glob(base.name+'*.inline')
    with dump.open() as stream:
        unit = next(int(m[1]) for s in stream if (m:=re.search(r'Starting with size (\d+)',s)))
    dump.unlink()
    result = dict(job, unit=unit, command=command, output=output, code_digest=code_digest(Path(output)))
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    print('compiled',obj,budget,'IPA',unit,flush=True)
    return result


def score(job):
    output = Path(job['output'])
    receipt = output.with_suffix('.score.json')
    if receipt.exists(): return json.loads(receipt.read_text())
    binary = output.with_suffix('.tomokv')
    command = shlex.split(next(s for s in reversed((ROOT/'build/wave4/build-rebuilt.log').read_text().splitlines())
                              if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    command[command.index('build/'+job['object'])] = str(output)
    command[command.index('-o')+1] = str(binary)
    command += ['-Wl,--strip-debug']
    subprocess.run(command,cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    post = identity.inventory(binary)
    refs = {arm:identity.inventory(path) for arm,path in identity.REFS.items()}
    rows = identity.compare(post, refs)
    result = dict(job, score=[sum(r['hot'] and not r['matches'] for r in rows),
                              sum(not r['matches'] for r in rows),sum(not r['equal'] for r in rows)],
                  linked_sha256=post['sha256'], link_command=command)
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    binary.unlink()
    print('scored',job['object'],job['budget'],result['score'],flush=True)
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True); DOC.mkdir(parents=True,exist_ok=True)
    phase = sys.argv[1]
    text = (ROOT/'Makefile').read_text()
    budgets = dict((m[1],int(m[2])) for m in re.finditer(r'\$\(BUILD_ROOT\)/([^:\n]+):[^\n]*large-unit-insns=(\d+)',text))
    head = {r['object']:r for r in json.loads((ROOT/'docs/compat2b/trials/initial/summary.json').read_text())
            if r['tree']=='headline'}
    oldmake = subprocess.check_output(['git','show','8656f9fa9:Makefile'],cwd=ROOT,text=True)
    oldbudgets = dict((m[1],int(m[2])) for m in re.finditer(r'\$\(BUILD_ROOT\)/([^:\n]+):[^\n]*large-unit-insns=(\d+)',oldmake))
    if phase=='initial':
        jobs=[dict(object=obj,budget=n) for obj,n in budgets.items()]
    elif phase=='scan':
        initial=json.loads((DOC/'initial.json').read_text()); jobs=[]
        for row in initial:
            obj=row['object']; center=oldbudgets[obj]+row['unit']-head[obj]['unit']
            # Preserve the established budget as an eligible control; evaluate
            # measured IPA headroom and neighbours on both sides.
            for n in sorted({row['budget'],center-8,center,center+8}):
                jobs.append(dict(object=obj,budget=n,derived=center))
    elif phase=='select':
        rows=json.loads((DOC/'scan.json').read_text())
        unique={}
        for row in rows:
            key=(row['object'],row['code_digest'])
            unique.setdefault(key,row)
        with ProcessPoolExecutor(max_workers=6) as pool:
            scores=list(pool.map(score,unique.values()))
        by={(r['object'],r['code_digest']):r for r in scores}
        choices=[]
        for obj,old in budgets.items():
            opts=[dict(r,score=by[(obj,r['code_digest'])]['score']) for r in rows if r['object']==obj]
            best=min(opts,key=lambda r:(r['score'],r['budget']!=old,abs(r['budget']-r['derived'])))
            choices.append(dict(object=obj,old=old,budget=best['budget'],score=best['score'],trials=opts))
        (DOC/'selected.json').write_text(json.dumps(choices,indent=2)+'\n')
        for r in choices: print(r['object'],r['old'],'->',r['budget'],r['score'])
        return
    else: raise ValueError(phase)
    with ProcessPoolExecutor(max_workers=32) as pool: rows=list(pool.map(trial,jobs))
    # A reused initial receipt acquires this phase's derivation metadata.
    rows=[dict(r,**j) for r,j in zip(rows,jobs)]
    (DOC/(phase+'.json')).write_text(json.dumps(rows,indent=2)+'\n')


if __name__=='__main__': main()
