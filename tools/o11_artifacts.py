#!/usr/bin/env python3
"""O11 kind-A behaviour twin: patch a copy's boot policy; never execute a server."""
import argparse
import hashlib
import json
from pathlib import Path

from lbstall_artifacts import Elf


def twin(source, output):
    source, output = Path(source), Path(output)
    assert source.resolve() != output.resolve(), 'control must be a separate file'
    elf = Elf(source)
    assert elf.kind != 1, 'expected a linked executable'
    matches = [s for name, s in elf.functions().items()
               if 'fused_local_rotation_policy' in name]
    assert len(matches) == 1, 'one noipa boot policy, without clones'
    symbol = matches[0]
    section = elf.sections[symbol['sec']]
    offset = section[4] + symbol['value'] - section[3]
    body = elf.body(symbol)
    if body.startswith(b'\xf3\x0f\x1e\xfa'):
        offset += 4
        body = body[4:]
    assert body == b'\xb8\x01\x00\x00\x00\xc3', 'expected mov eax,1; ret'
    patched = bytearray(elf.data)
    patched[offset + 1] = 0  # mov eax,0; ret -- same instructions, sizes, and addresses
    assert sum(a != b for a, b in zip(elf.data, patched)) == 1
    output.write_bytes(patched)
    output.chmod(source.stat().st_mode)
    control = Elf(output)
    assert elf.sections == control.sections and elf.symbols == control.symbols
    return {
        'kind': 'A: PRE rotation behaviour with POST text size and layout; L4 stays enabled',
        'post': str(source), 'pad': str(output), 'file_bytes': len(patched),
        'text_bytes': elf.sections[elf.names.index('.text')][5],
        'policy_symbol': symbol['name'], 'patch_offset': offset + 1,
        'original_bytes': '01', 'pad_bytes': '00',
        'post_sha256': hashlib.sha256(elf.data).hexdigest(),
        'pad_sha256': hashlib.sha256(patched).hexdigest(),
        'all_other_bytes_equal': True,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    receipt = twin(args.source, args.output)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
