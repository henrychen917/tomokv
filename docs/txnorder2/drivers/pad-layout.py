#!/usr/bin/env python3
"""Build PRE behaviour with the candidate's cold Server allocation size."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root=Path(__file__).resolve().parents[3]
pre=root/'build/txnorder2/pre-source'
dest=root/'build/txnorder2/pad-layout-source'
docs=root/'docs/txnorder2/pad-layout';docs.mkdir(exist_ok=True)
for name in ['src','third_party','tools']:
    shutil.copytree(pre/name,dest/name,dirs_exist_ok=True)
shutil.copy2(pre/'Makefile',dest/'Makefile')
path=dest/'src/core/server.h'
old=path.read_text()
needle='    std::unique_ptr<LbPlan> lb_plan_; // absent with both balancers off\n'
assert old.count(needle)==1
extra='\n    // Type-A control: unused cold tail, equal to the candidate Server tail.\n    alignas(64) unsigned char txnorder2_layout_padding_[32832]{};\n'
path.write_text(old.replace(needle,needle+extra))
command=['taskset','-c','64-95','make','-j32','all']
with (docs/'build.log').open('w') as f:
    rc=subprocess.run(command,cwd=dest,stdout=f,stderr=subprocess.STDOUT).returncode
record=dict(kind='A base: PRE behaviour plus unused candidate-sized Server tail',
    command=command,cwd=str(dest),exit_code=rc,mutation=dict(file='src/core/server.h',after=extra),
    source_before_sha256=hashlib.sha256(old.encode()).hexdigest(),
    source_after_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
if rc==0:
    binary=dest/'build/tomokv'
    record['sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    record['freshness']=subprocess.run(['taskset','-c','64-95','make','-q','all'],cwd=dest).returncode
    script=docs/'layout.gdb'
    script.write_text('set pagination off\npython\nimport gdb,json\nrows={}\nfor ns in ("tomo","tomo_db0"):\n t=gdb.lookup_type(ns+"::Server")\n rows[ns]=dict(size=int(t.sizeof),fields={f.name:dict(bitpos=int(f.bitpos),size=int(f.type.sizeof)) for f in t.fields() if hasattr(f,"bitpos")})\njson.dump(rows,open('+repr(str(docs/'layout.json'))+',"w"),indent=2)\nend\n')
    with (docs/'layout.log').open('w') as f:
        subprocess.run(['taskset','-c','64-95','gdb','-nx','-batch','-x',str(script),str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True)
    layout=json.loads((docs/'layout.json').read_text())
    assert layout['tomo']['size']==141568 and layout['tomo_db0']['size']==141184
(docs/'build.json').write_text(json.dumps(record,indent=2)+'\n')
assert rc==0
