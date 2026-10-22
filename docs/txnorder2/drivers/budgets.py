#!/usr/bin/env python3
"""Compile-only per-unit budget trials; preserve every opcode in the comparison."""
import concurrent.futures
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'));import ccfix_audit as cc
audit=cc.audit
OUT=ROOT/'docs/txnorder2/budgets';OUT.mkdir(parents=True,exist_ok=True)
BUILD=ROOT/'build/txnorder2/budgets';BUILD.mkdir(parents=True,exist_ok=True)
plans={
 'src/cmd/xshard.o':[141225,141737,142249,140713],
 'db0/src/cmd/xshard.o':[140131,140643,141155,139619],
 'src/core/genthread.o':[130241,130225,130257,130273],
 'src/core/rl2s.o':[163036,162972,163004,163068],
 'db0/src/core/reorder.o':[149160,149000,149080,149240],
}
recipe=subprocess.check_output(['make','-n','-W','Makefile','all'],cwd=ROOT,text=True).replace('\\\n',' ')
commands={}
for line in recipe.splitlines():
    if line.startswith('g++ '):
        cmd=shlex.split(line)
        if '-c' in cmd:commands[cmd[cmd.index('-o')+1]]=cmd
def run(item):
    obj,budget=item;label=obj.replace('/','_')+'-'+str(budget)
    output=BUILD/(label+'.o');command=commands['build/'+obj].copy()
    command=[f'large-unit-insns={budget}' if x.startswith('large-unit-insns=') else x for x in command]
    command[command.index('-o')+1]=str(output);command+=['-g0']
    with (BUILD/(label+'.log')).open('w') as f:
        rc=subprocess.run(['taskset','-c','64-95',*command],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT).returncode
    row=dict(object=obj,budget=budget,command=command,compile_exit=rc,output=str(output))
    if not rc:
        pre=audit.Elf(ROOT/'build/txnorder2/pre-source/build'/obj);post=audit.Elf(output)
        a,b=pre.functions(),post.functions();names=list(a)
        labels=subprocess.check_output(['c++filt'],input='\n'.join(names),text=True).splitlines()
        changed=[];total=0
        for symbol,name in zip(names,labels):
            if not audit.HOT.search(name):continue
            total+=1
            if symbol not in b or pre.canonical(a[symbol])!=post.canonical(b[symbol]):changed.append(name)
        row.update(total=total,changed=changed)
    (OUT/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    print(obj,budget,len(row.get('changed',[])),rc,flush=True)
    return row
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    rows=list(pool.map(run,[(obj,budget) for obj,values in plans.items() for budget in values]))
(OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
