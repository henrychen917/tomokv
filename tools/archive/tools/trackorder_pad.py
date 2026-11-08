#!/usr/bin/env python3
"""PAD-A behaviour twin: PRE deferral at POST's exact file/text/layout.

In each namespace, force tracking_flush_before_reply to return false, taking
PRE's deferred path. Only its entry instructions change; section sizes, symbol
addresses and all other bytes stay POST-identical. The oracle row is the control.
"""
import hashlib
import json
from pathlib import Path

from lbstall_artifacts import Elf


def main():
    post, pad = Path('build/tomokv'), Path('build/tomokv-PAD-A')
    elf = Elf(post)
    data = bytearray(post.read_bytes())
    patches = []
    symbols = [s for s in elf.symbols if 'tracking_flush_before_reply' in s['name']]
    assert len(symbols) == 2
    for symbol in symbols:
        section = elf.sections[symbol['sec']]
        pc = symbol['value']
        offset = section[4] + pc - section[3]
        if data[offset:offset + 4] == bytes.fromhex('f3 0f 1e fa'):
            offset += 4
            pc += 4
        original = bytes(data[offset:offset + 3])
        data[offset:offset + 3] = bytes.fromhex('31 c0 c3')  # xor eax,eax; ret
        patches.append(dict(symbol=symbol['name'], pc=hex(pc), offset=offset,
                            before=original.hex(), after=data[offset:offset + 3].hex()))
    pad.write_bytes(data)
    pad.chmod(0o755)
    other = Elf(pad)
    assert elf.sections == other.sections and elf.symbols == other.symbols
    changed = sum(a != b for a, b in zip(elf.data, other.data))
    assert 0 < changed <= 6
    receipt = dict(kind='A: PRE behaviour with exact POST layout', patches=patches,
                   post_sha256=hashlib.sha256(elf.data).hexdigest(),
                   pad_sha256=hashlib.sha256(other.data).hexdigest(),
                   text_bytes=elf.sections[elf.names.index('.text')][5],
                   changed_bytes=changed, sections_equal=True, symbols_equal=True)
    Path('docs/trackorder/pad.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
