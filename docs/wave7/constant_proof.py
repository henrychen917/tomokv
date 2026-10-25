#!/usr/bin/env python3
"""Supplement one strict mismatch with the exact eight-byte load target.

No normalization change: the strict inventory continues to mark the body changed.
"""
import gzip,json,re,subprocess,sys
from pathlib import Path
import identity
ROOT=identity.ROOT;sys.path.insert(0,str(ROOT/'tools'));from lbstall_artifacts import Elf
name='tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchCapture const*)'
paths={'persistfix2':identity.REFS['persistfix2'],'post':ROOT/'build/tomokv'}
bodies={a:json.load(gzip.open(ROOT/'docs/wave7/callsites'/(a+'.json.gz'),'rt'))[name][0] for a in paths}
a,b=bodies['persistfix2'],bodies['post'];assert a['encodings']==b['encodings']
diff=[i for i,(x,y) in enumerate(zip(a['ins'],b['ins'])) if x!=y]
assert len(a['ins'])==len(b['ins']) and len(diff)==1,diff
index=diff[0];result={}
for arm,path in paths.items():
 body=identity.inventory(path)['groups'][name][0];start=int(body['address'],16);off=int(bodies[arm]['ins'][index].split()[0],16)
 asm=subprocess.check_output(['objdump','-dw','--start-address='+hex(start+off),'--stop-address='+hex(start+off+7),str(path)],text=True)
 line=next(l for l in asm.splitlines() if re.match(r'\s*'+hex(start+off)[2:]+':',l))
 assert re.search(r'\bmov\s+.*\(%rip\),%rax\s+#',line),line
 target=int(re.search(r'#\s+([0-9a-f]+)',line)[1],16);elf=Elf(path)
 sec,= [s for s in elf.sections if s[3]<=target and target+8<=s[3]+s[5] and s[1]!=8 and s[2]&2]
 data=elf.data[sec[4]+target-sec[3]:sec[4]+target-sec[3]+8]
 result[arm]=dict(path=str(path),sha256=identity.audit.digest(path),offset=hex(off),load=line.strip(),target=hex(target),bytes=data.hex(),strict_instruction=bodies[arm]['ins'][index])
assert result['persistfix2']['bytes']==result['post']['bytes']
result['proof']='All other normalized instructions and every encoding match. The sole 64-bit RIP load reads the same eight bytes. Strict mismatch remains retained.'
(ROOT/'docs/wave7/identity/constant-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(result['proof'])
