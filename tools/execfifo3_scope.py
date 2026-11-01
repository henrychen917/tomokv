#!/usr/bin/env python3
"""Linked production instruction/memory scopes; finite fixtures, never rates."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess

os.environ['EXEC1S_CPUS']='96-111'
import exec1s_scope as scope

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/execfifo3'
MEMORY_SETUP='''
import sys
sys.path.insert(0, PYTHON_PATH)
import capstone
decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);decoder.detail=True
regions=[]
for i in range(int(gdb.parse_and_eval('scope_region_count'))):
 r=gdb.parse_and_eval('scope_regions[%d]'%i)
 regions.append((int(r['address']),int(r['size']),r['name'].string()))
memory=Counter();unknown=Counter();code_lines=set();accesses=0;stack_lines=set()
stack_top=int(gdb.parse_and_eval('$rsp'))
def reg(r):
 return int(gdb.parse_and_eval('$'+decoder.reg_name(r))) if r else 0
def memory_step(pc):
 global accesses
 ins=next(decoder.disasm(bytes(gdb.selected_inferior().read_memory(pc,15)),pc,count=1))
 code_lines.add(pc//64)
 if ins.mnemonic in ('lea','nop') or ins.mnemonic.startswith('prefetch'):return
 for operand in ins.operands:
  if operand.type!=capstone.x86.X86_OP_MEM:continue
  m=operand.mem
  addr=(pc+ins.size if m.base==capstone.x86.X86_REG_RIP else reg(m.base))+reg(m.index)*m.scale+m.disp
  if m.segment:addr+=int(gdb.parse_and_eval('$'+decoder.reg_name(m.segment)+'_base'))
  addr&=(1<<64)-1;accesses+=1
  for base,size,name in regions:
   if base<=addr<base+size:
    for line in range(addr//64-base//64,(addr+operand.size-1)//64-base//64+1):
     memory['%s+%d access=%d'%(name,line*64,operand.access)]+=1
    break
  else:
   if stack_top-65536<=addr<=stack_top+8192:
    unknown['stack/'+str(operand.access)]+=1
    stack_lines.update(range(addr//64,(addr+operand.size-1)//64+1))
   else:unknown[str(operand.access)]+=1
'''

def instrument():
    original=subprocess.run
    def run(command,*args,**kwargs):
        if isinstance(command,list) and 'gdb' in command and '-x' in command:
            path=Path(command[command.index('-x')+1]);text=path.read_text()
            setup=MEMORY_SETUP.replace('PYTHON_PATH',repr(str(BASE/'python')))
            text=text.replace('start.delete();gdb.execute',setup+'\nstart.delete();gdb.execute')
            text=text.replace('  counts[fn[3]]+=1','  memory_step(pc)\n  counts[fn[3]]+=1')
            text=text.replace('dict(total=sum(counts.values()),',
                'dict(memory=dict(memory),unknown_memory=dict(unknown),memory_operands=accesses,stack_cache_lines=len(stack_lines),'
                'instruction_cache_lines=len(code_lines),regions=[dict(name=n,size=s,alignment=b%64) for b,s,n in regions],total=sum(counts.values()),')
            path.write_text(text)
        return original(command,*args,**kwargs)
    subprocess.run=run

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=('commands','memory'),default='commands')
    p.add_argument('--arms',default='PRE,FIFO,POST-final')
    p.add_argument('--build-only',action='store_true');p.add_argument('--trace-only',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--namespaces',default='normal,db0');p.add_argument('--batches',default='1,32')
    p.add_argument('--commands',default='')
    p.add_argument('--overrides',type=Path)
    p.add_argument('--fresh',action='store_true',help='recount even an identical linked image')
    a=p.parse_args();assert os.sched_getaffinity(0)<=set(range(96,112))
    scope.OUT=ROOT/'docs/execfifo3'/a.kind;scope.OUT.mkdir(parents=True,exist_ok=True)
    scope.BUILD=BASE/(a.kind+'-scopes');scope.BUILD.mkdir(parents=True,exist_ok=True)
    scope.ARMS={arm:(BASE/(arm.lower()+'-source'),BASE/(arm.lower()+'-source')/'build') for arm in ('PRE','FIFO')}
    scope.ARMS['POST']=(ROOT,ROOT/'build');scope.SYMBOL_PREFIXES={}
    scope.ARMS['POST-final']=(ROOT,ROOT/'build')
    scope.ARMS['TRIAL']=(ROOT,ROOT/'build')
    if a.overrides:scope.OBJECT_OVERRIDES=json.loads(a.overrides.read_text())
    if a.kind=='memory':scope.FIXTURE=ROOT/'tests/execfifo3_scope.cc';instrument()
    arms=a.arms.split(',');namespaces=a.namespaces.split(',')
    if a.fresh:
        for arm in arms:
            for ns in namespaces:
                for path in scope.OUT.glob(arm+'-'+ns+'-*.log'):
                    if not path.name.endswith('-build.log'):path.unlink()
    if not a.trace_only:
        for arm in arms:
            for ns in namespaces:scope.build(arm,ns)
    if a.build_only:return
    commands=a.commands.split(',') if a.commands else (['GET','SET','INCR'] if a.kind=='memory' else ['GET','SET','INCR','MGET','MSET'])
    cases=[(arm,ns,cmd,mode,batch,atomic,local)
           for arm in arms for ns in namespaces for cmd in commands for mode in ('1s','2s')
           for batch in map(int,a.batches.split(','))
           for atomic in ((0,1) if cmd=='MSET' else (1,))
           for local in ((0,1) if a.kind=='memory' and mode=='1s' else (-1,))]
    with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:rows=list(pool.map(scope.trace,cases))
    scope.save(scope.OUT/('results-'+a.arms+'.json'),rows)
    keys=('namespace','command','mode','batch','atomic','threshold');pairs=[]
    for row in rows:
        if row['arm']=='PRE':continue
        pre=next((r for r in rows if r['arm']=='PRE' and all(r[k]==row[k] for k in keys)),None)
        if pre is None:continue
        pair={k:row[k] for k in keys}|dict(arm=row['arm'],pre=pre['total'],post=row['total'],delta=row['total']-pre['total'])
        if a.kind=='memory':
            fields=set(pre['memory'])|set(row['memory'])
            pair['memory_delta']={k:row['memory'].get(k,0)-pre['memory'].get(k,0) for k in sorted(fields)
                                  if row['memory'].get(k,0)!=pre['memory'].get(k,0)}
            pair['operand_delta']=row['memory_operands']-pre['memory_operands']
            pair['code_lines']=[pre['instruction_cache_lines'],row['instruction_cache_lines']]
            old_lines={k.split(' access=')[0] for k in pre['memory']}
            new_lines={k.split(' access=')[0] for k in row['memory']}
            pair['added_object_lines']=sorted(new_lines-old_lines)
        pairs.append(pair)
    scope.save(scope.OUT/('comparison-'+a.arms+'.json'),pairs)
    print('Comparisons',len(pairs),'positive instruction deltas',sum(r['delta']>0 for r in pairs))
    candidate=[r for r in pairs if r['arm'].startswith('POST')]
    assert all(r['delta']<=0 for r in candidate),'POST adds production-scope instructions'
    if a.kind=='memory':
        assert all(r['operand_delta']<=0 and not r['added_object_lines'] for r in candidate),\
            'POST adds explicit memory operands or an object line'

if __name__=='__main__':main()
