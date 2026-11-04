#!/usr/bin/env python3
"""Compress completed proof binaries' debug sections; preserve every allocated byte/address."""
import fcntl,hashlib,json,os,struct,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/flipfix7/debug-compression.json'
lock=(ROOT/'build/flipfix7/debug-compression.lock').open('w')
fcntl.flock(lock,fcntl.LOCK_EX)
rows=json.loads(DOC.read_text()) if DOC.exists() else []
seen={r['path']: r['after_sha256'] for r in rows}
def allocated(data):
 h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
 result=[]
 for i in range(h[12]):
  s=struct.unpack_from('<IIQQQQIIQQ',data,h[6]+i*h[11])
  if s[2]&2:result.append((s[3],s[5],None if s[1]==8 else data[s[4]:s[4]+s[5]]))
 return result
paths = list((ROOT/'build').iterdir())
paths += list((ROOT/'build').glob('*-controls/*/unit'))
paths += list((ROOT/'build').glob('*-controls/*/db0-unit'))
for path in sorted(paths, key=lambda p: p.stat().st_size if p.is_file() else 0, reverse=True):
 if not path.is_file() or path.is_symlink() or (path.name.startswith('tomokv') or path.name=='blockfix-cost'):continue
 if time.time()-path.stat().st_mtime<30:continue
 with path.open('rb') as f:
  if f.read(4)!=b'\x7fELF':continue
 metadata=path.stat()
 before=path.read_bytes()
 if seen.get(str(path.relative_to(ROOT))) == hashlib.sha256(before).hexdigest():continue
 temp=path.with_name(path.name+'.debug-compress')
 subprocess.run(['objcopy','--compress-debug-sections=zlib',str(path),str(temp)],check=True)
 after=temp.read_bytes();assert allocated(before)==allocated(after),path
 os.utime(temp,ns=(metadata.st_atime_ns,metadata.st_mtime_ns))
 os.replace(temp,path)
 rows.append(dict(path=str(path.relative_to(ROOT)),before_bytes=len(before),after_bytes=len(after),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest(),allocated_sections_identical=True))
 DOC.write_text(json.dumps(rows,indent=2)+'\n')
 print(path.name,len(before),len(after),flush=True)
