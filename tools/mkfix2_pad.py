#!/usr/bin/env python3
"""Build A's type-A control: PRE reply timing in A's exact linked layout.

Only the successful-MSET materialization arm is bypassed, in both namespaces.
All code, section sizes and addresses stay in place. Fail closed if GCC's checked
instruction sequence differs. This is an artifact tool, never a runtime knob.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from lbstall_artifacts import Elf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    assert args.source.resolve() != args.output.resolve(), 'patch a separate artifact'
    elf = Elf(args.source)
    data = bytearray(elf.data)
    patches = []
    for name, symbol in elf.functions().items():
        if 'xshard_flush_commits' not in name or '.cold' in name:
            continue
        body = elf.body(symbol)
        # Op::zc_shard at 0xb4 receives kScatterReplyMarker (-6).
        marker = bytes.fromhex('c7 83 b4 00 00 00 fa ff ff ff')
        assert body.count(marker) == 1, (name, 'completed-MSET marker')
        end = body.index(marker) + len(marker)
        assert body[end] == 0xe9, (name, 'materialization rejoins completion')
        after = end + 5 + struct.unpack_from('<i', body, end + 1)[0]
        # The MSET-only aborted check immediately precedes reply_ok's body.
        check = bytes.fromhex('41 0f b6 80 48 03 00 00 84 c0 0f 85')
        matches = []
        for at in range(max(0, end - 128), end - len(check)):
            if body[at:at + len(check)] != check:
                continue
            branch = at + len(check) - 2
            if branch + 6 + struct.unpack_from('<i', body, branch + 2)[0] == after:
                matches.append(branch)
        assert len(matches) == 1, (name, 'unique guard to completion')
        at = matches[0]
        replacement = b'\xe9' + struct.pack('<i', after - (at + 5)) + b'\x90'
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3] + at
        patches.append(dict(symbol=name, file_offset=offset,
                            before=body[at:at + 6].hex(), after=replacement.hex()))
        data[offset:offset + 6] = replacement
    assert len(patches) == 2, 'both database namespaces must be patched'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.chmod(0o755)
    receipt = dict(kind='A: behaviour twin',
                   behaviour='PRE opaque atomic-MSET completion, otherwise A (which has no B/C)',
                   layout='A: all ELF section sizes and addresses unchanged',
                   source=str(args.source), output=str(args.output),
                   source_sha256=hashlib.sha256(elf.data).hexdigest(),
                   sha256=hashlib.sha256(data).hexdigest(), patches=patches)
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
