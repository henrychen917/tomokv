#!/usr/bin/env python3
"""Exercise name-sensitive ELF controls on copied symbol tables, without booting.

A rename only changes ELF symbol metadata. Each negative removes the selected
role from that metadata; the production executable is never modified.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--binary',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--only', help='one control (storesize needs its serverless unit as --binary)')
a=p.parse_args();a.root=a.root.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(a.root/'tools'))
import source_tokens as cpp
symbols=[line.split()[-1] for line in subprocess.check_output(['nm',str(a.binary)],text=True).splitlines() if line.split()]
renames={name:cpp.actual_symbol(name) for name in symbols if name.startswith('_Z') and cpp.actual_symbol(name)!=name}
source=a.binary.resolve()
if renames:
    mapping=a.output/'renames.txt';mapping.write_text(''.join(old+' '+new+'\n' for old,new in renames.items()))
    source=a.output/'renamed'
    subprocess.run(['objcopy','--redefine-syms='+str(mapping),str(a.binary),str(source)],check=True)
current_names=[renames.get(name,name) for name in symbols]
cases=[
 ('hll','from _serverfix_mutant import zero_hll_count;zero_hll_count(binary,output/"hll")',r'3hll5count'),
 ('perfex_clock','from perfex_checks import clock_check;clock_check(binary)',r'7ExLoopTI[\s\S]*3runEv'),
 ('perfex_batch','from perfex_checks import batch_check;batch_check(binary)',r'11drain_tasks|34drain_tasks_read_local_interleaved'),
 ('cfgfix_clock','from cfgfix2 import clock_ranges;print(clock_ranges(str(binary)))',r'21configure_object_idle|7install'),
 ('r7_fifo','from r7shadow_pad import twin;print(twin(binary,output/"fifo","fifo"))',r'17reorder_available'),
 ('r7_shadow','from r7shadow_pad import twin;print(twin(binary,output/"shadow","shadow"))',r'16shadow_available'),
 ('lbplanner','from lbplanner_pad import plan;print(plan(binary))',r'13lb_pass_begin'),
 ('lbosc3','from lbosc3_pad import plan;print(plan(binary))',r'12lbosc3_level'),
 ('storesize','from storesize_artifacts import pad;print(pad(binary,output/"storesize"))',r'24storesize_published_route'),
]
rows=[]
for name,command,pattern in cases:
    if (a.only and name != a.only) or (not a.only and name == 'storesize'):
        continue
    def run(binary):
        script="import sys;sys.path[:0]=['tests','tools'];from pathlib import Path;binary=Path(sys.argv[1]);output=Path(sys.argv[2]);"+command
        return subprocess.run([sys.executable,'-c',script,str(binary),str(a.output)],cwd=a.root,
            env=dict(os.environ,LC_ALL='C'),capture_output=True,text=True,timeout=120)
    positive=run(source)
    targets=[symbol for symbol in current_names if re.search(pattern,cpp.canonical_symbol(symbol))]
    if not targets:raise ValueError('negative symbol inventory empty: '+name)
    mapping=a.output/'broken-symbols.txt';mapping.write_text(''.join(symbol+' a1_missing_'+str(i)+'\n' for i,symbol in enumerate(targets)))
    broken=a.output/'broken'
    subprocess.run(['objcopy','--redefine-syms='+str(mapping),str(source),str(broken)],check=True)
    negative=run(broken)
    row=dict(tool=name,renamed_symbols=len(renames),removed_symbols=len(targets),positive=positive.returncode,
             negative=negative.returncode,stdout=positive.stdout,stderr=positive.stderr,negative_stderr=negative.stderr)
    row['passed']=row['positive']==0 and row['negative']!=0
    rows.append(row);(a.output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('PASS' if row['passed'] else 'FAIL',name,'positive',positive.returncode,'negative',negative.returncode,flush=True)
    if not row['passed']:print(positive.stderr+negative.stderr,flush=True)
raise SystemExit(int(not all(row['passed'] for row in rows)))
