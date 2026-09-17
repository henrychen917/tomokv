#!/usr/bin/env python3
"""Create the round-2 kind-A decoder twin offline; never execute the server."""
import argparse
import hashlib
import json
from pathlib import Path
from lbstall_artifacts import Elf


def twin(source, output):
    elf = Elf(source)
    assert elf.kind != 1 and Path(source).resolve() != Path(output).resolve()
    data = bytearray(elf.data)
    sites = sorted({(s['sec'], s['value']) for s in elf.symbols
                    if s['name'].startswith('tomo_multidb2_pad_')})
    assert sites, 'no annotated KeyExt branches'
    changed = set()
    for sec, value in sites:
        section = elf.sections[sec]
        assert section[2] & 4
        at = section[4] + value - section[3]
        if data[at] == 0x75:  # JNZ rel8 -> JMP rel8
            data[at] = 0xeb
            changed.add(at)
        else:  # JNZ rel32 -> NOP; JMP rel32 (same end address and displacement)
            assert data[at:at + 2] == b'\x0f\x85', (hex(value), data[at:at + 6].hex())
            data[at:at + 2] = b'\x90\xe9'
            changed.update((at, at + 1))
    assert len(data) == len(elf.data)
    assert {i for i, (a, b) in enumerate(zip(data, elf.data)) if a != b} == changed
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    pad = Elf(output)
    assert pad.sections == elf.sections and pad.symbols == elf.symbols
    return dict(kind='A: behaviour twin', control='round-1 independent key pointer/length/namespace decoder',
                source=str(source), output=str(output), branches=len(sites), changed_bytes=len(changed),
                unchanged='every section size, symbol address, and byte outside the annotated branch opcodes',
                source_sha256=hashlib.sha256(elf.data).hexdigest(),
                pad_sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(twin(args.source, args.output), indent=2))
