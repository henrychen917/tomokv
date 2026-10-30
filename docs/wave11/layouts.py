#!/usr/bin/env python3
"""Offline DWARF layout checks on all three retained arms; never starts an inferior."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
os.sched_setaffinity(0,set(range(64,96)))
expected={'Op':336,'Client':1984,'ThreadCtx':1408,'Shard':1440,'FlatStore':944,'Rob<64>':192,'AtomicEntry':144,'Config':624}
cold=['IoLoop::ClimonConn','NotifyBatch','(anonymous namespace)::ClientMeta','(anonymous namespace)::ScriptContext']
code='''import gdb,json
names=NAMES
rows={}
for name in names:
 t=gdb.lookup_type(name)
 rows[name]={'size':t.sizeof,'fields':[{'name':f.name,'bitpos':f.bitpos,'type':str(f.type)} for f in t.fields() if hasattr(f,'bitpos')]}
print('LAYOUT_JSON='+json.dumps(rows))
'''
results={}
for arm in ('PRE','POST','PAD-A'):
 binary=ROOT/'build/wave11'/('tomokv-'+arm)
 names=[ns+'::'+name for ns in ('tomo','tomo_db0') for name in list(expected)+cold]
 program=code.replace('NAMES',repr(names))
 output=subprocess.check_output(['gdb','-nx','-q','--batch',str(binary),'-ex','python exec('+repr(program)+')'],text=True,stderr=subprocess.STDOUT)
 row=json.loads(next(s.removeprefix('LAYOUT_JSON=') for s in output.splitlines() if s.startswith('LAYOUT_JSON=')))
 for ns in ('tomo','tomo_db0'):
  for name,size in expected.items():assert row[ns+'::'+name]['size']==size,(arm,ns,name,row[ns+'::'+name]['size'])
 results[arm]=dict(sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),layouts=row)
for ns in ('tomo','tomo_db0'):
 for name in cold:
  assert results['POST']['layouts'][ns+'::'+name]==results['PAD-A']['layouts'][ns+'::'+name],(ns,name)
(ROOT/'docs/wave11/layouts.json').write_text(json.dumps(results,indent=2)+'\n')
print('PASS all eight fixed sizes in both namespaces, all three arms; cold POST/PAD-A layouts match')
