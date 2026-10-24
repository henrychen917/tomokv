#!/usr/bin/env python3
"""Offline PAD-A and isolated broken-writer test control; never patch POST in place."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def symbols(path):
    rows={}
    for line in subprocess.check_output(['nm','-S','--defined-only',str(path)],text=True).splitlines():
        v=line.split()
        if len(v)==4 and v[2] in ('t','T','w','W'):
            rows[v[3]]=(int(v[0],16),int(v[1],16))
    return rows


def offset(data,address,size):
    assert data[:6]==b'\x7fELF\x02\x01'
    phoff=struct.unpack_from('<Q',data,32)[0]
    phsize,phnum=struct.unpack_from('<HH',data,54)
    loads=[struct.unpack_from('<IIQQQQQQ',data,phoff+i*phsize) for i in range(phnum)]
    found=[p[2]+address-p[3] for p in loads if p[0]==1 and p[3]<=address and address+size<=p[3]+p[5]]
    assert len(found)==1
    return found[0]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pre',type=Path,required=True)
    p.add_argument('--post',type=Path,required=True)
    p.add_argument('--pad',type=Path,required=True)
    p.add_argument('--broken-writer',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    args=p.parse_args()
    before=args.pre.read_bytes();post=args.post.read_bytes()
    old=symbols(args.pre);new=symbols(args.post)
    pad=bytearray(post);broken=bytearray(post);patches=[]
    # Relocation-free leaf: all data accesses are member offsets, the only
    # branch targets its own return. Fail closed if compiler/source changes it.
    original=bytes.fromhex('f30f1efa488b979007000031c04885d27412488b4240482b423848c1f80469c0abaaaaaac3')
    for ns in ('4tomo','8tomo_db0'):
        name='_ZN'+ns+'24multi_session_watch_sizeERKNS_6ClientE'
        addr,size=old[name];at=offset(before,addr,size)
        assert before[at:at+size]==original,(name,'unexpected PRE leaf')
        addr,size=new[name];at=offset(post,addr,size)
        assert size>=len(original),(name,size)
        replacement=original+b'\x90'*(size-len(original))
        patches.append(dict(arm='PAD-A',symbol=name,address=hex(addr),offset=at,
                            before=post[at:at+size].hex(),after=replacement.hex()))
        pad[at:at+size]=replacement
        name='_ZN'+ns+'23multi_plain_write_readyERNS_5ShardERNS_2OpE'
        addr,size=new[name];at=offset(post,addr,size)
        assert post[at:at+4]==bytes.fromhex('f30f1efa') and size>10
        at+=4
        replacement=bytes.fromhex('b801000000c3')
        broken[at:at+6]=replacement
        patches.append(dict(arm='broken-writer',symbol=name,address=hex(addr+4),offset=at,
                            before=post[at:at+6].hex(),after=replacement.hex()))
    for path,data in ((args.pad,pad),(args.broken_writer,broken)):
        assert path.resolve() not in (args.pre.resolve(),args.post.resolve())
        path.write_bytes(data);path.chmod(args.post.stat().st_mode)
        assert symbols(path)==new,'symbol placement or footprint changed'
    receipt=dict(pad_kind='A: PRE behaviour with exact POST text size, function addresses and data layout',
                 broken_writer='Test-only unconditional readiness bypass; never a candidate or merit arm',
                 patches=patches,binaries={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (args.pre,args.post,args.pad,args.broken_writer)})
    args.receipt.write_text(json.dumps(receipt,indent=2)+'\n')
if __name__=='__main__':main()
