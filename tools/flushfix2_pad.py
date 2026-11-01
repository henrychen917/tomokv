#!/usr/bin/env python3
"""PAD-A behaviour twin: legacy FLUSH routing in the candidate's exact ELF layout.

Disable the cold routing predicate and the cold snapshot continuation pump in
both namespace images. No range can be installed; the retained AllShards path
performs PRE's tombstone/clear and legacy AOF Flush. No server is started here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from lbstall_artifacts import Elf


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--receipt', type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert a.output.resolve().is_relative_to(root/'build')
    assert a.source.resolve() != a.output.resolve()
    elf = Elf(a.source)
    data = bytearray(elf.data)
    changes = []
    for stem in ('xshard_flush_command', 'xshard_flush_snapshot_progress'):
        symbols = [s for s in elf.functions().values() if stem in s['name'] and '.' not in s['name']]
        assert len(symbols) == 2, (stem, symbols)
        for symbol in symbols:
            section = elf.sections[symbol['sec']]
            offset = section[4] + symbol['value'] - section[3]
            if data[offset:offset+4] == b'\xf3\x0f\x1e\xfa':
                offset += 4  # preserve CET's indirect-entry landing pad
            before = bytes(data[offset:offset+3])
            data[offset:offset+3] = b'\x31\xc0\xc3'  # xor eax,eax; ret
            changes.append(dict(symbol=symbol['name'], offset=offset, before=before.hex(), after='31c0c3'))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(a.source, a.output)
    a.output.write_bytes(data)
    check = Elf(a.output)
    assert elf.sections == check.sections and elf.symbols == check.symbols
    restored = bytearray(data)
    for change in changes:
        offset = change['offset']
        restored[offset:offset+3] = bytes.fromhex(change['before'])
    assert restored == elf.data
    receipt = dict(kind='A: behaviour twin', source=str(a.source), output=str(a.output),
                   source_sha256=hashlib.sha256(elf.data).hexdigest(),
                   output_sha256=hashlib.sha256(data).hexdigest(),
                   sections_and_symbols_identical=True, changes=changes,
                   residual_work='Candidate budgets and dormant range-aware code retained; only FLUSH routing and its snapshot pump disabled.')
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    a.receipt.write_text(json.dumps(receipt, indent=2)+'\n')
    print(receipt['output_sha256'])


if __name__ == '__main__':
    main()
