#!/usr/bin/env python3
"""Classify parser buffer, TLS and otherwise unlabelled load sites."""
import json
import os
from pathlib import Path
import shutil
import execfifo3_scope as driver

ROOT=Path(__file__).resolve().parents[1]

def main():
    assert os.sched_getaffinity(0)<=set(range(96,112))
    scope=driver.scope
    scope.OUT=ROOT/'docs/execfifo3/memory-sites'
    scope.OUT.mkdir(parents=True,exist_ok=True)
    scope.BUILD=ROOT/'build/execfifo3/memory-scopes'
    # Inspect the existing linked probes; do not change their code or receipts.
    driver.MEMORY_SETUP=driver.MEMORY_SETUP.replace('memory=Counter();', '''
regions.append((int(gdb.parse_and_eval('$fs_base')),64,'ThreadTLS'))
for base,size,name in list(regions):
 if name.startswith('Client'):
  client=gdb.parse_and_eval('((tomo_db0::Client*)%d)'%base)
  regions.append((int(client['rbuf_']),int(client['rcap_']),name+'Rbuf'))
memory=Counter();''')
    driver.MEMORY_SETUP=driver.MEMORY_SETUP.replace(
        "else:unknown[str(operand.access)]+=1", """else:
    unknown[str(operand.access)]+=1
    fn=at(pc)
    key='site/'+fn[3]+'+'+hex(pc-fn[0])+' '+ins.mnemonic+' '+ins.op_str
    unknown[key]+=1
""")
    driver.instrument()
    rows=[]
    for arm in ('PRE','FIFO','POST-final'):
        receipt=ROOT/'docs/execfifo3/memory'/(arm+'-db0-build.json')
        shutil.copy2(receipt,scope.OUT/receipt.name)
        rows.append(scope.trace((arm,'db0','PARSE-SET','1s',32,1,0)))
    scope.save(scope.OUT/'results.json',rows)
    before,old,after=rows
    assert after['total']==before['total']
    assert after['memory']==before['memory']
    assert {k:v for k,v in after['unknown_memory'].items() if not k.startswith('site/')}=={
        k:v for k,v in before['unknown_memory'].items() if not k.startswith('site/')}
    delta={k:old['memory'].get(k,0)-before['memory'].get(k,0)
           for k in old['memory'] if old['memory'].get(k,0)!=before['memory'].get(k,0)}
    scope.save(scope.OUT/'fifo-extra-loads.json',delta)
    print(json.dumps(delta,indent=2))

if __name__=='__main__':main()
