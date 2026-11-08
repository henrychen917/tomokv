#!/usr/bin/env python3
"""Compress debug data in completed unit binaries; preserve executable text."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]

def compressed(path):
    with path.open('rb') as f:
        header=f.read(64)
        if header[:6]!=b'\x7fELF\x02\x01':return True
        offset=struct.unpack_from('<Q',header,40)[0]
        size,count,names=struct.unpack_from('<HHH',header,58)
        f.seek(offset);raw=f.read(size*count)
        sections=[struct.unpack_from('<IIQQQQIIQQ',raw,i*size) for i in range(count)]
        section=sections[names];f.seek(section[4]);strings=f.read(section[5])
        return any(strings[s[0]:].split(b'\0',1)[0]==b'.debug_info' and s[2]&0x800 for s in sections)

def main():
    assert os.sched_getaffinity(0)<=set(range(96,112))
    record=ROOT/'docs/execfifo3/unit-debug-compression.json'
    rows=json.loads(record.read_text()) if record.exists() else []
    active=set()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            args=(entry/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
            if '-o' in args:active.add(((entry/'cwd').resolve()/args[args.index('-o')+1]).resolve())
        except (OSError,ValueError,UnicodeError):pass
    saved=0
    for path in sorted((ROOT/'build').glob('*-unit')):
        if not path.is_file() or path in active or not os.access(path,os.X_OK):continue
        stat=path.stat()
        if stat.st_size<50_000_000 or time.time()-stat.st_mtime<30 or compressed(path):continue
        temp=path.with_suffix('.compact')
        before=subprocess.check_output(['objcopy','--dump-section','.text=/dev/stdout',str(path),'/dev/null'])
        subprocess.run(['objcopy','--compress-debug-sections=zstd',str(path),str(temp)],check=True)
        after=subprocess.check_output(['objcopy','--dump-section','.text=/dev/stdout',str(temp),'/dev/null'])
        assert before==after,path
        current=path.stat()
        if (current.st_ino,current.st_size,current.st_mtime_ns)!=(stat.st_ino,stat.st_size,stat.st_mtime_ns):
            temp.unlink();continue
        temp.replace(path);saved+=stat.st_size-path.stat().st_size
        rows.append(dict(path=str(path.relative_to(ROOT)),before_bytes=stat.st_size,after_bytes=path.stat().st_size,
                         text_sha256=hashlib.sha256(before).hexdigest(),compressed_ns=time.time_ns()))
        record.write_text(json.dumps(rows,indent=2)+'\n')
    print('Debug-only bytes saved:',saved)

if __name__=='__main__':main()
