#!/usr/bin/env python3
"""Offline kind-A control: keep POST layout and select FIFO or inherited R7 behaviour."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lbstall_artifacts import Elf


def twin(source, output, scope='shadow'):
    source, output = Path(source), Path(output)
    assert source.resolve() != output.resolve(), 'control must be a separate file'
    elf = Elf(source)
    assert elf.kind != 1, 'expected a linked executable'
    functions = elf.functions()
    suffix = '17reorder_availableEv' if scope == 'fifo' else '2r716shadow_availableEv'
    patched = bytearray(elf.data)
    patches = []
    # The boot-selected DB-0 and multidb runtimes each own their capability.
    # Patch every linked variant, including single-variant serverless fixtures.
    for prefix in ('_ZN4tomo', '_ZN8tomo_db0'):
        if not any(name.startswith(prefix) for name in functions):
            continue
        symbol = functions[prefix + suffix]
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        body = elf.body(symbol)
        if body.startswith(b'\xf3\x0f\x1e\xfa'):
            offset += 4
            body = body[4:]
        assert body == b'\xb8\x01\x00\x00\x00\xc3', 'expected bool true; ret'
        # Change only the immediate. Instructions, padding, symbols and sections stay exact.
        patched[offset + 1] = 0
        patches.append({'capability_symbol': symbol['name'], 'patch_offset': offset + 1})
    assert patches, 'no reorder runtime found'
    assert sum(a != b for a, b in zip(elf.data, patched)) == len(patches)
    output.write_bytes(patched)
    output.chmod(source.stat().st_mode)
    control = Elf(output)
    assert elf.sections == control.sections and elf.symbols == control.symbols
    return {
        'kind': ('A: PRE FIFO behaviour with POST text size and layout; all reorder disabled'
                 if scope == 'fifo' else
                 'A: PRE R7 behaviour with POST text size and layout; shadow disabled'),
        'post': str(source), 'pad': str(output), 'file_bytes': len(patched),
        'text_bytes': elf.sections[elf.names.index('.text')][5],
        'patches': patches,
        **(patches[0] if len(patches) == 1 else {}),
        'original_byte': '01', 'pad_byte': '00',
        'post_sha256': hashlib.sha256(elf.data).hexdigest(),
        'pad_sha256': hashlib.sha256(patched).hexdigest(),
        'all_other_bytes_equal': True,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--scope', choices=('shadow', 'fifo'), default='shadow')
    args = parser.parse_args()
    receipt = twin(args.source, args.output, args.scope)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
