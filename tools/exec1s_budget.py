#!/usr/bin/env python3
"""Compile-only exec1s inline-budget controls; no workload/rate measurements."""
import argparse, concurrent.futures, json, re, shlex, subprocess
from pathlib import Path
from lbstall_artifacts import Elf, HOT
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/exec1s/budgets'; OUT.mkdir(exist_ok=True,parents=True)
BUILD=ROOT/'build/exec1s/budgets'; BUILD.mkdir(exist_ok=True,parents=True)
UNITS=[prefix+suffix for prefix in ['src/','db0/src/'] for suffix in ['cmd/xshard.o']]
def recipes(root):
    text=subprocess.check_output(['make','-n','-W','Makefile','all'],cwd=root,text=True).replace('\\\n',' ')
    result={}
    for line in text.splitlines():
        if line.startswith('g++ '):
            cmd=shlex.split(line)
            if '-c' in cmd: result[cmd[cmd.index('-o')+1].removeprefix('build/')]=cmd
    return result
PRE=ROOT/'build/exec1s/pre-source'
COMMANDS={'pre':recipes(PRE),'post':recipes(ROOT)}
def run(item):
    arm,unit,value=item; label=arm+'-'+unit.replace('/','_')+'-'+str(value)
    output=BUILD/(label+'.o'); dump=BUILD/(label+'.inline')
    cmd=COMMANDS[arm][unit].copy()
    oldbudget=int(next(x.split('=')[1] for x in cmd if x.startswith('large-unit-insns=')))
    if value is not None:cmd=[f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x for x in cmd]
    cmd[cmd.index('-o')+1]=str(output)
    cmd=['taskset','-c','80-95',*cmd,'-g0',f'-fdump-ipa-inline={dump}']
    receipt=OUT/(label+'.json')
    if receipt.exists():return json.loads(receipt.read_text())
    with (BUILD/(label+'.log')).open('w') as f:
        subprocess.run(cmd,cwd=PRE if arm=='pre' else ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    text=dump.read_text(); initial=int(re.search(r'Starting with size (\d+)',text)[1]); dump.unlink()
    a,b=Elf(PRE/'build'/unit),Elf(output);old,new=a.functions(),b.functions()
    names=list(old); labels=subprocess.check_output(['c++filt'],input='\n'.join(names),text=True).splitlines()
    changed=[];total=0
    for symbol,name in zip(names,labels):
        if not HOT.search(name) and not re.search(r'xshard_(prepare|execute)\(',name):continue
        total+=1
        if symbol not in new or a.canonical(old[symbol])!=b.canonical(new[symbol]):changed.append(name)
    row=dict(arm=arm,unit=unit,budget=oldbudget if value is None else value,initial=initial,command=cmd,output=str(output),changed=changed,total=total)
    receipt.write_text(json.dumps(row,indent=2)+'\n');print(label,initial,len(changed),flush=True)
    return row
def main():
    p=argparse.ArgumentParser();p.add_argument('--survey',action='store_true');p.add_argument('--unit');p.add_argument('values',nargs='*',type=int);a=p.parse_args()
    jobs=[(arm,unit,None) for arm in ['pre','post'] for unit in UNITS] if a.survey else [('post',a.unit,v) for v in a.values]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:rows=list(pool.map(run,jobs))
    (OUT/('survey.json' if a.survey else a.unit.replace('/','_')+'-trials.json')).write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
