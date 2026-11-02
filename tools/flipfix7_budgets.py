#!/usr/bin/env python3
"""Source-accurate compile-only budget derivation; no server or rates."""
import argparse, concurrent.futures, json, re, shlex, subprocess
from pathlib import Path
from lbstall_artifacts import Elf
ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT/'build/flipfix7/pre-source'
BUILD=ROOT/'build/flipfix7/budgets'; DOC=ROOT/'docs/flipfix7/budgets'
EARLY=None
UNITS=['src/main.o','db0/src/main.o','src/cmd/xshard.o','db0/src/cmd/xshard.o']

def recipe(root,obj):
 text=subprocess.check_output(['make','-B','-n','build/'+obj],cwd=root,text=True)
 return shlex.split(next(s for s in reversed(text.splitlines()) if s.startswith('g++ ') and s.endswith(' -o build/'+obj)))

def run(job):
 arm,unit,budget=job;root=PRE if arm=='pre' else ROOT
 tag=arm+'-'+unit.replace('/','_')+'-'+str(budget)+(f'-early{EARLY}' if EARLY is not None else '');receipt=DOC/(tag+'.json')
 if receipt.exists():return json.loads(receipt.read_text())
 command=recipe(root,unit);base=int(next(x.split('=')[1] for x in command if x.startswith('large-unit-insns=')))
 if budget is not None:command=[f'large-unit-insns={budget}' if x.startswith('large-unit-insns=') else x for x in command]
 if EARLY is not None: command=[f'early-inlining-insns={EARLY}' if x.startswith('early-inlining-insns=') else x for x in command]
 dest=BUILD/(tag+'.o');dump=BUILD/(tag+'.inline');command[command.index('-o')+1]=str(dest)
 command=['taskset','-c','48-60',*command,'-g0',f'-fdump-ipa-inline={dump}']
 with (BUILD/(tag+'.log')).open('w') as f:subprocess.run(command,cwd=root,stdout=f,stderr=subprocess.STDOUT,check=True)
 with dump.open() as f:initial=next(int(m[1]) for line in f if (m:=re.search(r'Starting with size (\d+)',line)))
 dump.unlink()
 old,new=Elf(PRE/'build'/unit),Elf(dest);a,b=old.functions(),new.functions();different=[]
 for name,fn in a.items():
  if name not in b or old.canonical(fn)!=new.canonical(b[name]):different.append(name)
 row=dict(arm=arm,unit=unit,budget=base if budget is None else budget,initial=initial,command=command,output=str(dest),changed=different,total=len(a))
 receipt.write_text(json.dumps(row,indent=2)+'\n');print(tag,initial,len(different),flush=True);return row

def main():
 global EARLY
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['survey','derive','trial']);p.add_argument('--unit');p.add_argument('--values');p.add_argument('--early',type=int);args=p.parse_args();EARLY=args.early
 BUILD.mkdir(parents=True,exist_ok=True);DOC.mkdir(parents=True,exist_ok=True)
 if args.phase=='survey':jobs=[(arm,unit,None) for arm in ['pre','post'] for unit in UNITS]
 elif args.phase=='derive':
  rows=json.loads((DOC/'survey.json').read_text());by={(r['arm'],r['unit']):r for r in rows};jobs=[]
  for unit in UNITS:
   pre,post=by['pre',unit],by['post',unit];center=pre['budget']+post['initial']-pre['initial'];jobs.append(('post',unit,center))
 else:jobs=[('post',args.unit,int(n)) for n in args.values.split(',')]
 with concurrent.futures.ThreadPoolExecutor(8) as pool:rows=list(pool.map(run,jobs))
 (DOC/(args.phase+('-'+args.unit.replace('/','_') if args.unit else '')+(f'-early{EARLY}' if EARLY is not None else '')+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
