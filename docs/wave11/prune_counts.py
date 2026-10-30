#!/usr/bin/env python3
"""Keep counts and hashes; retire completed probes and instruction step logs."""
import gzip, hashlib, json, os, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave11';INS=DOC/'instructions'
os.sched_setaffinity(0,set(range(64,96)))
keep={'pre','pre-session','pre-control','scriptfix3','scriptfix3-dispatch-v2',
      'scriptfix3-gc','final-post','final-session','final-control','final-dispatch','slot-inline-gc'}
bindings=list(DOC.glob('binding-*.json'))
assert len(bindings)>=13 and all(json.loads(p.read_text())['passed'] for p in bindings)
records=[];archive={}
for p in sorted(INS.rglob('*')):
    if not p.is_file():continue
    relative=p.relative_to(INS)
    retain=len(relative.parts)==2 and relative.parts[0] in keep and p.suffix=='.json'
    if retain:continue
    data=p.read_bytes()
    row=dict(path=str(p.relative_to(ROOT)),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    if p.name.endswith('.sites.gz'):
        sites=json.loads(gzip.decompress(data))['sites']
        row.update(distinct_instruction_addresses=len(sites),instructions=sum(sites.values()))
    else:
        try:archive[str(relative)]=json.loads(data)
        except (ValueError,UnicodeError):archive[str(relative)]=data.decode(errors='replace')
    records.append(row)
with gzip.open(DOC/'archived-count-details.json.gz','wt') as f:json.dump(archive,f)
with gzip.open(DOC/'pruned-step-traces.json.gz','wt') as f:json.dump(records,f)
for row in records:(ROOT/row['path']).unlink()
for p in sorted(INS.rglob('*'),reverse=True):
    if p.is_dir() and not any(p.iterdir()):p.rmdir()
probes=ROOT/'build/wave11/counts'
files=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
       for p in probes.rglob('*') if p.is_file()]
with gzip.open(DOC/'pruned-probes.json.gz','wt') as f:json.dump(files,f)
shutil.rmtree(probes)
print('retired',len(records),'trace/detail files and',len(files),'probe files;',
      round(sum(r['bytes'] for r in files)/2**30,2),'GiB of probes; aggregate counts retained')
