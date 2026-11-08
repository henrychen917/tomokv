#!/usr/bin/env python3
"""PAD-A: PRE publication behaviour in an exact-layout copy of the POST ELF.

Force the equality/return edge of every DWARF-attributed `newer <= drawn`
comparison. The initial safe CAS and the non-last path remain intact. The extra
sequence load and comparison still execute: this is a behaviour/layout control,
not a claim that PAD has PRE's cycle cost. Never install this negative control.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from lbstall_artifacts import Elf


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--header', type=Path, default=Path('src/core/server.h'))
    p.add_argument('--receipt', type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert a.output.resolve().is_relative_to(root / 'build')
    assert a.source.resolve() != a.output.resolve()
    line, = [i for i, text in enumerate(a.header.read_text().splitlines(), 1)
             if 'if (newer <= drawn ||' in text]
    elf = Elf(a.source)
    assert elf.kind != 1
    data = bytearray(elf.data)
    changes = []
    location = function = ''
    previous = ''
    proc = subprocess.Popen(['objdump', '-dlw', str(a.source)], stdout=subprocess.PIPE, text=True)
    for text in proc.stdout:
        if re.match(r'^[0-9a-f]+ <', text):
            function = text.strip()
        if re.match(r'^/.*:[0-9]+', text):
            location = text.strip()
        ins = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S+)\s*(.*)', text)
        if not ins:
            continue
        address, raw, op = int(ins[1], 16), bytes.fromhex(ins[2]), ins[3]
        if re.search(r'/server\.h:' + str(line) + r'(?:\s|$)', location) and op in ('jb', 'ja', 'jbe', 'jae'):
            assert previous.startswith('cmp'), (previous, text)
            assert len(raw) in (2, 6)
            if op in ('jb', 'ja'):
                # Strict inequality excludes equality: fall through to the return path.
                patched = b'\x90' * len(raw)
            else:
                # Equality takes the branch. NOP+JMP preserves a near Jcc's end address.
                patched = b'\xeb' + raw[1:] if len(raw) == 2 else b'\x90\xe9' + raw[2:]
            section, = [s for s in elf.sections if s[2] & 4 and s[3] <= address < s[3] + s[5]]
            offset = section[4] + address - section[3]
            assert data[offset:offset + len(raw)] == raw
            data[offset:offset + len(raw)] = patched
            changes.append(dict(function=function, location=location, address=hex(address),
                                offset=offset, before=raw.hex(), after=patched.hex(), instruction=text.strip()))
        previous = op + ' ' + ins[4]
    assert proc.wait() == 0
    assert changes and any('atomic_commit_publish' in c['function'] for c in changes)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(a.source, a.output)
    a.output.write_bytes(data)
    check = Elf(a.output)
    assert elf.sections == check.sections, 'section addresses/sizes/layout changed'
    assert elf.symbols == check.symbols, 'function addresses/sizes changed'
    # Every other byte, including all non-text loadable sections, is exact POST.
    restored = bytearray(data)
    for c in changes:
        raw = bytes.fromhex(c['before'])
        restored[c['offset']:c['offset'] + len(raw)] = raw
    assert bytes(restored) == elf.data
    receipt = dict(kind='A: behaviour twin', source=str(a.source), output=str(a.output),
                   source_sha256=hashlib.sha256(elf.data).hexdigest(),
                   output_sha256=hashlib.sha256(data).hexdigest(), changes=changes,
                   sections_and_symbols_identical=True,
                   residual_work='POST sequence recheck load and comparison remain; catch-up disabled')
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    a.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'changes'}), flush=True)
    print('patched publisher comparisons:', len(changes))


if __name__ == '__main__':
    main()
