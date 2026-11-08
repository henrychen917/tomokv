#!/usr/bin/env python3
"""PAD-A for periodic reclamation: retain POST layout, restore PRE idle retention.

Only IdleBuffers::visit entry points are replaced by `return false`. The compatibility
fixes and removal of the old request-time sheds are shared with POST. Thus this is a
behavior twin for the new cold periodic mechanism, not a reverse patch of every fix.
No shipped binary contains a switch or a test hook.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('post', type=Path)
    p.add_argument('pad', type=Path)
    p.add_argument('receipt', type=Path)
    a = p.parse_args()
    original = a.post.read_bytes()
    data = bytearray(original)
    assert data[:6] == b'\x7fELF\x02\x01'
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize) for i in range(phnum)]
    patches = []
    for line in subprocess.check_output(['nm', '-S', '-C', str(a.post)], text=True).splitlines():
        m = re.fullmatch(r'([0-9a-f]+) ([0-9a-f]+) [tTwW] ((?:tomo|tomo_db0)::IdleBuffers::visit\(.*)', line)
        if not m:
            continue
        address, size = int(m[1], 16), int(m[2], 16)
        offsets = [p[2] + address - p[3] for p in loads if p[0] == 1 and
                   p[3] <= address and address + size <= p[3] + p[5]]
        assert len(offsets) == 1 and size >= 7
        offset = offsets[0]
        if data[offset:offset + 4] == bytes.fromhex('f30f1efa'):
            offset += 4  # retain the CET landing pad
        patch = bytes.fromhex('31c0c3')
        patches.append(dict(symbol=m[3], address=hex(address), offset=offset,
                            before=data[offset:offset + len(patch)].hex(), after=patch.hex()))
        data[offset:offset + len(patch)] = patch
    assert len(patches) == 2, patches
    a.pad.write_bytes(data)
    a.pad.chmod(a.post.stat().st_mode)
    a.receipt.write_text(json.dumps(dict(kind='A: behavior twin of periodic reclamation',
        scope=__doc__, patches=patches, changed_bytes=sum(x != y for x, y in zip(original, data)),
        post_sha256=hashlib.sha256(original).hexdigest(),
        pad_sha256=hashlib.sha256(data).hexdigest()), indent=2) + '\n')


if __name__ == '__main__':
    main()
