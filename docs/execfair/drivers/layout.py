#!/usr/bin/env python3
"""Read DWARF layouts without running a binary."""
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/execfair/layout';OUT.mkdir(exist_ok=True)
types=['Op','Client','ThreadCtx','Shard','FlatStore','Rob<64>','AtomicEntry','Config',
       'ExLoopT<false>','ExLoopT<true>','MultiExecState','TxnGroupAttempt','TxnOwnerCounters','ScatterState']
for arm,binary in [('PRE','build/pre/tomokv'),('POST','build/tomokv'),('PAD-A','build/pad-a/tomokv')]:
 if not (ROOT/binary).exists():continue
 script=ROOT/'build'/('layout-'+arm+'.gdb')
 output=OUT/(arm+'.json')
 script.write_text('set pagination off\nset auto-load off\npython\nimport gdb,json\nrows={}\n'+
  'for ns in ("tomo", "tomo_db0"):\n'+
  f' for name in {types!r}:\n'+
  '  t=gdb.lookup_type(ns+"::"+name)\n'+
  '  rows[ns+"::"+name]=dict(size=t.sizeof,fields={f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,"bitpos")})\n'+
  f'json.dump(rows,open({str(output)!r},"w"),indent=2)\nend\n')
 subprocess.run(['gdb','-nx','-batch','-x',str(script),str(ROOT/binary)],check=True,
                stdout=(OUT/(arm+'.log')).open('w'),stderr=subprocess.STDOUT)
pre=json.loads((OUT/'PRE.json').read_text());post=json.loads((OUT/'POST.json').read_text())
rows=[]
for name,before in pre.items():
 after=post[name]
 rows.append(dict(type=name,pre=before['size'],post=after['size'],
                  changed_old_fields={k:[v,after['fields'].get(k)] for k,v in before['fields'].items()
                                      if v!=after['fields'].get(k)}))
(OUT/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
