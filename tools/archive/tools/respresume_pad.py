#!/usr/bin/env python3
"""PAD (A), behavior twin: discard partial argv with POST's exact text layout.

Patch only resp_suspend's entry to return Incomplete. A frontier starts empty
and never gets populated, so resume re-enters at the array header on every read.
All complete-frame instructions, callers, section sizes and addresses stay POST.
The candidate's no-replay exceptional-header decoder and NT4.3 removal remain in
this control; POST/PAD isolates retained partial argv, not those shared changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('post', type=Path)
    ap.add_argument('pad', type=Path)
    ap.add_argument('receipt', type=Path)
    args = ap.parse_args()
    data = bytearray(args.post.read_bytes())
    assert data[:6] == b'\x7fELF\x02\x01', 'ELF64 little endian required'
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, phoff+i*phsize) for i in range(phnum)]
    symbols = subprocess.check_output(['nm', '-S', '-C', str(args.post)], text=True)
    changed = []
    for line in symbols.splitlines():
        m = re.match(r'([0-9a-f]+) ([0-9a-f]+) [tTWw] (.*::resp_suspend\(.*)', line)
        if not m: continue
        address, size = int(m[1], 16), int(m[2], 16)
        offsets = [p[2]+address-p[3] for p in loads
                   if p[0] == 1 and p[3] <= address and address+size <= p[3]+p[5]]
        assert len(offsets) == 1 and size >= 10, line
        offset = offsets[0]
        # Preserve CET landing; mov eax,1; ret. No metadata or argv is retained.
        if data[offset:offset+4] == bytes.fromhex('f30f1efa'): offset += 4
        patch = bytes.fromhex('b801000000c3')
        changed.append(dict(symbol=m[3], address=hex(address), offset=offset,
                            before=data[offset:offset+6].hex(), after=patch.hex()))
        data[offset:offset+6] = patch
    assert len(changed) == 2, ('must patch both namespaces', changed)
    args.pad.write_bytes(data)
    args.pad.chmod(args.post.stat().st_mode)
    args.receipt.write_text(json.dumps(dict(kind='A: behavior twin', patches=changed,
        post_sha256=hashlib.sha256(args.post.read_bytes()).hexdigest(),
        pad_sha256=hashlib.sha256(data).hexdigest()), indent=2)+'\n')
    print('PAD-A: patched both suspension helpers; text layout unchanged')


if __name__ == '__main__': main()
