#!/usr/bin/env python3
"""PAD-A: skip only the new refreshes in POST; preserve every ELF address.

DWARF inline stacks identify refresh_command_clock, including inlined copies.
Each five-byte call becomes a jump past BOTH the realtime and conditional LRU
updates. Existing pass cuts, op pins, sections, symbols and all other bytes stay.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
from rlfence_artifacts import instructions

def main():
    source, destination = map(Path,sys.argv[1:3])
    raw=subprocess.check_output(['objdump','-dw',str(source)],text=True)
    code=instructions(raw)
    clocksites=[(i,row[0]) for i,row in enumerate(code) if 'call' in row[2] and '<clock_gettime@' in row[2]]
    stacks=subprocess.check_output(['addr2line','-a','-f','-i','-e',str(source),*[hex(a) for _,a in clocksites]],text=True)
    marked=set()
    for block in re.split(r'(?m)^(?=0x[0-9a-f]+$)',stacks):
        if 'refresh_command_clock' in block:
            marked.add(int(block.splitlines()[0],16))
    assert marked, 'DWARF did not identify any added clock reads'
    elf=Elf(source); data=bytearray(elf.data); patches=[]
    def offset(at):
        return next(s[4]+at-s[3] for s in elf.sections if s[2]&4 and s[3]<=at<s[3]+s[5])
    for i,at in clocksites:
        if at not in marked: continue
        row=code[i]
        assert row[1][0]==0xe8 and len(row[1])==5
        # The command clock is the only store to cached_now_ms_ in this slice.
        j=next(j for j in range(i+1,i+25) if re.fullmatch(r'mov\s+%\w+,0x158\(%\w+\)',code[j][2]))
        assert code[j+1][2].startswith(('je ', 'jne ')),code[j+1]
        assert re.fullmatch(r'cmpb\s+\$0x0,0x188\(%\w+\)',code[j-1][2]),code[j-1]
        branch=code[j+1][2].split()
        end=int(branch[1],16) if branch[0]=='je' else code[j+2][0]
        # Both ends are instruction boundaries in the same containing body.
        target=next(r for r in code if r[0]==end)
        assert target[3]==row[3]
        after=b'\xe9'+struct.pack('<i',end-at-5)
        off=offset(at); assert data[off:off+5]==row[1]
        data[off:off+5]=after
        patches.append(dict(address=at,offset=off,target=end,function=row[3],
                            before=row[1].hex(),after=after.hex(),
                            skipped=[r[2] for r in code[i+1:j+2]]))
    assert len(patches)==len(marked)
    destination.write_bytes(data); destination.chmod(source.stat().st_mode)
    twin=Elf(destination)
    assert elf.sections==twin.sections and elf.symbols==twin.symbols
    restored=bytearray(twin.data)
    for p in patches:
        off=p['offset']; restored[off:off+5]=bytes.fromhex(p['before'])
    assert restored==elf.data, 'bytes outside specified jumps changed'
    result=dict(kind='A: PRE clock placement/behaviour, exact POST text size and layout',
                pre_source='8656f9fa9',post_sha256=hashlib.sha256(elf.data).hexdigest(),
                pad_sha256=hashlib.sha256(twin.data).hexdigest(),patches=patches,
                caveat='POST stack/register allocation and pre-call timespec initialization remain; no new realtime/LRU update executes.')
    (ROOT/'docs/clockcut/pad.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PAD-A:',len(patches),'refresh calls bypassed; all other bytes and layout identical')
if __name__=='__main__': main()
