#!/usr/bin/env python3
"""Drop only unit/control DWARF; preserve every allocated section and merit arm."""
import hashlib,json,struct,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
keep={ROOT/'build'/x for x in ('tomokv','tomokv-pre','tomokv-pad-a')}
keep.add(ROOT/'build/pre-objects/build/tomokv')
keep_inodes={(p.stat().st_dev,p.stat().st_ino) for p in keep}
def allocated(p):
    with p.open('rb') as f:
        h=f.read(64);off=struct.unpack_from('<Q',h,40)[0];size,num=struct.unpack_from('<HH',h,58)
        f.seek(off);headers=f.read(size*num);rows=[]
        for i in range(num):
            sh=struct.unpack_from('<IIQQQQIIQQ',headers,i*size)
            if not sh[2]&2:continue
            digest=None
            if sh[1]!=8:
                f.seek(sh[4]);digest=hashlib.sha256(f.read(sh[5])).hexdigest()
            rows.append((sh[1],sh[2],sh[3],sh[5],sh[8],digest))
        return rows
rows=[]
for p in sorted((ROOT/'build').rglob('*')):
    if not p.is_file() or p.is_symlink() or p in keep:continue
    if (p.stat().st_dev,p.stat().st_ino) in keep_inodes:continue
    with p.open('rb') as f:h=f.read(20)
    if h[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(h[16:18],'little') not in (2,3):continue
    before=p.stat().st_size;image=allocated(p)
    subprocess.run(['strip','--strip-debug',str(p)],check=True)
    assert image==allocated(p),('allocated section changed',p)
    rows.append(dict(path=str(p.relative_to(ROOT)),before=before,after=p.stat().st_size,allocated_equal=True))
(ROOT/'docs/datafix2/lean-build.json').write_text(json.dumps(rows,indent=2)+'\n')
print('stripped',len(rows),'unit/control executables; saved',sum(x['before']-x['after'] for x in rows),'bytes; allocated sections unchanged')
