#!/usr/bin/env python3
"""Read ELF runtime sections; optional lossless debug compression of owned unit binaries."""
import hashlib, json, os, struct, subprocess, sys
from pathlib import Path

def image(path):
    data=Path(path).read_bytes()
    assert data[:6]==b'\x7fELF\x02\x01', 'ELF64 little-endian required'
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
    entry, phoff, shoff, phsize, phnum, shsize, shnum, names=h[4],h[5],h[6],h[9],h[10],h[11],h[12],h[13]
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*shsize) for i in range(shnum)]
    strings=sections[names]; names_data=data[strings[4]:strings[4]+strings[5]]
    rows=[]
    for name,kind,flags,addr,offset,size,link,info,align,entsize in sections:
        if not flags & 2: continue
        label=names_data[name:names_data.index(0,name)].decode()
        rows.append(dict(name=label,type=kind,flags=flags,address=addr,size=size,alignment=align,
                         sha256=None if kind==8 else hashlib.sha256(data[offset:offset+size]).hexdigest()))
    headers=[struct.unpack_from('<IIQQQQQQ',data,phoff+i*phsize) for i in range(phnum)]
    return dict(entry=entry,program_headers=headers,sections=rows)

def compact(paths,receipt):
    rows=[]
    for path in map(Path,paths):
        assert path.resolve().is_relative_to(Path.cwd()/'build')
        assert path.name!='tomokv' and 'rlfix5' not in path.parts, 'frozen/release arms excluded'
        if not path.is_file() or path.read_bytes()[:4]!=b'\x7fELF': continue
        old=path.stat(); before=image(path); old_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        output=path.with_name(path.name+'.debug-compressed')
        subprocess.run(['objcopy','--compress-debug-sections=zlib',str(path),str(output)],check=True)
        assert image(output)==before, 'allocated sections or loader metadata changed'
        if output.stat().st_size>=old.st_size:
            output.unlink();continue
        output.chmod(old.st_mode)
        os.utime(output,ns=(old.st_atime_ns,old.st_mtime_ns))
        output.replace(path)
        rows.append(dict(path=str(path),old_bytes=old.st_size,new_bytes=path.stat().st_size,
                         old_sha256=old_sha,new_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),runtime_image_equal=True))
    Path(receipt).write_text(json.dumps(rows,indent=2)+'\n')
    print('Lossless debug compression saved',sum(r['old_bytes']-r['new_bytes'] for r in rows),'bytes',flush=True)

if __name__=='__main__': compact(sys.argv[2:],sys.argv[1])
