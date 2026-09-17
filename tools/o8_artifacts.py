#!/usr/bin/env python3
"""Make O8's kind-A behaviour twin offline; never execute a server."""
import argparse
import hashlib
import json
from pathlib import Path

from lbstall_artifacts import Elf


def twin(source, output):
    source, output = Path(source), Path(output)
    assert source.resolve() != output.resolve(), 'patch only a separate copy'
    elf = Elf(source)
    assert elf.kind != 1, 'expected a linked executable'
    policies = [s for name, s in elf.functions().items() if 'o8_batch_depth_enabled' in name]
    assert len(policies) == 1, 'one noipa startup policy, without clones'
    policy = policies[0]
    section = elf.sections[policy['sec']]
    offset = section[4] + policy['value'] - section[3]
    body = elf.body(policy)
    if body.startswith(b'\xf3\x0f\x1e\xfa'):
        offset += 4  # preserve the CET landing instruction
        body = body[4:]
    assert len(body) >= 3 and body[:3] != b'\x31\xc0\xc3', 'unpatched predicate required'
    patched = bytearray(elf.data)
    patched[offset:offset + 3] = b'\x31\xc0\xc3'  # false; ret
    output.write_bytes(patched)
    output.chmod(source.stat().st_mode)
    pad = Elf(output)
    assert elf.sections == pad.sections and elf.symbols == pad.symbols
    assert elf.data[:offset] == pad.data[:offset]
    assert elf.data[offset + 3:] == pad.data[offset + 3:]
    return {
        'kind': 'A: PRE owner-batch behaviour with POST text size/layout',
        'scope': 'O8 disabled; O1, O6, L4 prebuild and flipctl unchanged',
        'post': str(source), 'pad': str(output),
        'file_bytes': len(patched), 'text_bytes': elf.sections[elf.names.index('.text')][5],
        'policy_symbol': policy['name'], 'patch_offset': offset,
        'original_bytes': body[:3].hex(), 'pad_bytes': '31c0c3',
        'post_sha256': hashlib.sha256(elf.data).hexdigest(),
        'pad_sha256': hashlib.sha256(pad.data).hexdigest(),
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
