#!/usr/bin/env python3
"""Count one bounded EXEC, following every call (including indirect/library calls).

This is a serverless instruction audit, not a throughput or latency benchmark.
The markers enclose prepare, scheduled owner turns and retirement for two INCRs.
Counts include fixture glue and user-space dependencies except vDSO clock reads:
single-stepping across the kernel's vvar update makes their retry loop diverge.
Those calls run to return and are separately counted, with no invented instruction
estimate. Kernel instructions are not visible to GDB. REP single-step iterations
are debugger steps, not hardware-retired instructions. No sampling/extrapolation.
"""
import concurrent.futures
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/txnorder2/exec-instructions'
BUILD = ROOT / 'build/txnorder2/exec-instructions'
OUT.mkdir(exist_ok=True)
BUILD.mkdir(exist_ok=True)

def run(case):
    arm, ns, mode, shape = case
    label = '-'.join(case)
    binary = ROOT / 'build/txnorder2/paths-final2b/exec' / (arm+'-'+ns) / 'probe'
    data = OUT / (label+'.json')
    script = BUILD / (label+'.gdb')
    script.write_text('''set pagination off
set confirm off
set auto-load off
set print thread-events off
python
import gdb,json,collections,re
begin=gdb.Breakpoint('scatter_trace_begin')
end=gdb.Breakpoint('scatter_trace_end')
gdb.execute(RUN,to_string=True)
begin.delete()
gdb.execute('finish',to_string=True)
end_pc=int(gdb.parse_and_eval('(void*)&scatter_trace_end'))
counts=collections.Counter()
vdso_line=next(s for s in gdb.execute('info proc mappings',to_string=True).splitlines() if '[vdso]' in s)
vdso_lo,vdso_hi=[int(s,16) for s in re.findall(r'0x[0-9a-f]+',vdso_line)[:2]]
vdso_calls=0
for steps in range(500000):
 pc=int(gdb.parse_and_eval('$pc'))
 if pc==end_pc: break
 if vdso_lo <= pc < vdso_hi:
  vdso_calls+=1
  gdb.execute('finish',to_string=True)
  continue
 counts[pc]+=1
 gdb.execute('stepi',to_string=True)
else: raise RuntimeError('EXEC did not reach its end marker in 500000 steps')
rows=[]
arch=gdb.selected_frame().architecture()
for pc,count in sorted(counts.items()):
 rows.append(dict(pc=hex(pc),count=count,symbol=gdb.execute('info symbol '+hex(pc),to_string=True).strip(),asm=arch.disassemble(pc,count=1)[0]['asm']))
json.dump(dict(steps=sum(counts.values()),excluded_vdso_calls=vdso_calls,sites=rows),open(OUTPUT,'w'),indent=2)
end.delete()
gdb.execute('continue',to_string=True)
end
'''.replace('RUN',repr('run '+shape+' '+mode)).replace('OUTPUT',repr(str(data))))
    command = ['taskset','-c','72-79','gdb','-nx','-batch','-x',str(script),str(binary)]
    with (OUT/(label+'.log')).open('w') as log:
        try:
            rc = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    complete = 'PASS linked production EXEC' in (OUT/(label+'.log')).read_text()
    result = dict(arm=arm,namespace=ns,mode=mode,shape=shape,command=command,
                  sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  returncode=rc,fixture_completed=complete)
    if data.exists():
        trace=json.loads(data.read_text())
        result['steps_per_exec']=trace['steps']
        result['excluded_vdso_calls']=trace['excluded_vdso_calls']
        result['rep_steps']=sum(r['count'] for r in trace['sites'] if r['asm'].startswith(('rep ','repz ','repnz ')))
        functions=collections.Counter()
        for site in trace['sites']:
            name=re.sub(r' \+ \d+ in section.*', '', site['symbol'])
            name=re.sub(r' in section.*', '', name)
            if name.startswith('No symbol matches'): name='<no debug symbol>'
            functions[name]+=site['count']
        small=OUT/'function-counts';small.mkdir(exist_ok=True)
        (small/data.name).write_text(json.dumps(dict(steps=trace['steps'],
            excluded_vdso_calls=trace['excluded_vdso_calls'],
            functions=dict(functions.most_common())),indent=2)+'\n')
    (OUT/(label+'-result.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(label,rc,complete,result.get('steps_per_exec'),flush=True)
    return result

if __name__ == '__main__':
    cases=[(a,n,m,s) for a in ['pre','post'] for n in ['normal','db0']
           for m in ['1s','2s'] for s in ['single','cross']]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        rows=list(pool.map(run,cases))
    (OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    assert all(r['returncode']==0 and r['fixture_completed'] for r in rows)
