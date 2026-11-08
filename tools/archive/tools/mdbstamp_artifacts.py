#!/usr/bin/env python3
"""Offline kind-A stamp control: PRE behavior in POST's exact ELF layout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from lbstall_artifacts import Elf


def twin(source, output):
    elf = Elf(source)
    assert elf.kind != 1 and Path(source).resolve() != Path(output).resolve()
    symbol, = [s for s in elf.symbols
               if s['name'] == '_ZN4tomoL19stamp_regular_rangeERNS_2OpE']
    body = elf.body(symbol)
    section = elf.sections[symbol['sec']]
    at = section[4] + symbol['value'] - section[3]
    if body.startswith(bytes.fromhex('f30f1efa')):
        at += 4
    assert symbol['size'] >= 7
    # Both overloads must call this one outline, never an inlined copy.
    disassembly = subprocess.check_output(['objdump', '-dw', str(source)], text=True)
    calls = re.findall(r'call\s+[0-9a-f]+ <_ZN4tomoL19stamp_regular_rangeERNS_2OpE>', disassembly)
    assert len(calls) == 2, f'expected two stamp callers, found {len(calls)}'
    data = bytearray(elf.data)
    data[at:at + 3] = bytes.fromhex('31c0c3')  # xor eax,eax; ret before any prologue
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    pad = Elf(output)
    assert pad.sections == elf.sections and pad.symbols == elf.symbols
    assert data[:at] == elf.data[:at] and data[at + 3:] == elf.data[at + 3:]
    return dict(kind='A: behaviour twin', source=str(source), output=str(output),
                construction='return false from stamp_regular_range; all commands use PRE cold body',
                limitations='retains one extra helper call/return and class-branch versus PRE',
                changed_bytes=3, helper_bytes=symbol['size'], helper_file_offset=at,
                text_bytes=section[5],
                source_sha256=hashlib.sha256(elf.data).hexdigest(),
                pad_sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(twin(args.source, args.output), indent=2))
