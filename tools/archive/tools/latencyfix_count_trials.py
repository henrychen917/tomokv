#!/usr/bin/env python3
"""Link the production command-scope witness with one compile-only budget trial."""
import argparse,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('unit')
p.add_argument('values',nargs='+',type=int)
p.add_argument('--main',type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
recipes=subprocess.check_output(['make','-Bn','-f','Makefile','-f','tools/latencyfix_counts.mk','build/latencyfix-counts'],text=True,cwd=root)
link,=[shlex.split(x) for x in recipes.splitlines() if x.startswith('g++ ') and ' -o build/latencyfix-counts ' in x]
reference=[json.loads(x)for x in (root/'docs/latencyfix/counts-pre.jsonl').read_text().splitlines()]
out=root/'build/latencyfix/count-trials'
out.mkdir(exist_ok=True)
summary=[]
for value in a.values:
 cmd=link.copy()
 if a.main:cmd[cmd.index('build/src/main.o')]=str(a.main)
 trial=root/'build/latencyfix/budgets/scan'/a.unit.replace('/','_')/(str(value)+'.o')
 cmd[cmd.index('build/'+a.unit)]=str(trial)
 binary=out/(a.unit.replace('/','_')+'-'+str(value))
 cmd[cmd.index('-o')+1]=str(binary)
 subprocess.run(cmd,check=True,cwd=root,stdout=subprocess.DEVNULL)
 rows=[json.loads(x) for x in subprocess.check_output([binary],text=True,cwd=root).splitlines()]
 diffs=[dict(mode=x['mode'],command=x['command'],batch=x['batch'],slowlog_us=x['slowlog_us'],
             delta=min(y['counts'])-min(x['counts']))for x,y in zip(reference,rows)]
 record=dict(unit=a.unit,value=value,counts=rows,diffs=diffs)
 summary.append(record)
 print(a.unit,value,[(d['mode'],d['batch'],d['slowlog_us'],d['delta'])for d in diffs if d['command']=='GET'],flush=True)
 binary.unlink()
(root/'docs/latencyfix/budgets'/('counts-'+a.unit.replace('/','_')+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
