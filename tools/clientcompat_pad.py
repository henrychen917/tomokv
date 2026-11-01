#!/usr/bin/env python3
"""PAD-A: PRE compatibility behavior at POST's exact ELF/text/data layout.

The cold production selector returns true. Replacing its two namespace bodies
with `xor eax,eax; ret` restores PRE's pause exemption, displayed owner count,
queue-time tracking, MULTI control refusals, and immediate TRACKING ON reply.
No ordinary GET/SET/INCR/MGET/MSET path calls the selector.
"""
import argparse
import hashlib
import json
from pathlib import Path

from lbstall_artifacts import Elf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--post', type=Path, default=Path('build/clientcompat/POST/tomokv'))
    parser.add_argument('--pad', type=Path, default=Path('build/clientcompat/PAD-A/tomokv'))
    args = parser.parse_args()
    elf = Elf(args.post)
    data = bytearray(elf.data)
    patches = []
    symbols = [s for s in elf.symbols if 'clientcompat_postEv' in s['name']]
    assert len(symbols) == 2, symbols
    for symbol in symbols:
        section = elf.sections[symbol['sec']]
        pc = symbol['value']
        offset = section[4] + pc - section[3]
        if data[offset:offset+4] == bytes.fromhex('f3 0f 1e fa'):
            offset += 4
            pc += 4
        assert data[offset:offset+6] == bytes.fromhex('b8 01 00 00 00 c3')
        original = bytes(data[offset:offset+3])
        data[offset:offset+3] = bytes.fromhex('31 c0 c3')
        patches.append(dict(symbol=symbol['name'], pc=hex(pc), offset=offset,
                            before=original.hex(), after='31c0c3'))
    args.pad.parent.mkdir(parents=True, exist_ok=True)
    args.pad.write_bytes(data)
    args.pad.chmod(0o755)
    pad = Elf(args.pad)
    assert elf.sections == pad.sections and elf.symbols == pad.symbols
    changed = sum(a != b for a, b in zip(elf.data, pad.data))
    assert 0 < changed <= 6
    receipt = dict(kind='A: PRE behavior with exact POST text and data layout',
                   patches=patches, changed_bytes=changed, sections_equal=True,
                   symbols_equal=True,
                   post_sha256=hashlib.sha256(elf.data).hexdigest(),
                   pad_sha256=hashlib.sha256(pad.data).hexdigest(),
                   text_bytes=elf.sections[elf.names.index('.text')][5])
    target = Path('docs/clientcompat/pad.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
