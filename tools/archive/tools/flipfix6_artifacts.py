#!/usr/bin/env python3
"""PAD-A behaviour twin: POST layout with PRE's session-null FLIP predicate.

Only the pending-null branch in each namespace changes: it becomes a two-byte
NOP, so every non-null session takes the existing false return. A null session
still requires zero WATCH refs and all unchanged connection drain clauses.
All other POST bytes, section sizes and symbol addresses remain identical.
"""
import argparse
import json
from pathlib import Path

from flipfix5_artifacts import sections, symbol, function_rows, sha

SYMBOLS = ('_ZNK4tomo6Client28flip_migration_protocol_idleEv',
           '_ZNK8tomo_db06Client28flip_migration_protocol_idleEv')


def build(source, dest, receipt):
    data = Path(source).read_bytes()
    patched = bytearray(data)
    text_vma, text_off, _ = sections(source)['.text']
    patches = []
    for name in SYMBOLS:
        start, size, rows = function_rows(source, name)
        matches = [(i, pc, raw, asm) for i, (pc, raw, asm) in enumerate(rows)
                   if asm.startswith('cmpq') and '$0x0,0x50(' in asm]
        assert len(matches) == 1, (name, matches)
        i, _, _, _ = matches[0]
        pc, raw, asm = rows[i + 1]
        assert len(raw) == 2 and raw[0] == 0x74 and asm.startswith('je '), rows[i:i + 4]
        assert rows[i + 2][2] == 'xor    %eax,%eax' and rows[i + 3][2] == 'ret', rows[i:i + 4]
        offset = text_off + pc - text_vma
        assert data[offset:offset + 2] == raw
        patches.append(dict(symbol=name, address=pc, offset=offset,
                            before=raw.hex(), after='6690'))
        patched[offset:offset + 2] = bytes.fromhex('6690')
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(patched)
    dest.chmod(0o755)
    assert len(data) == len(patched) and sections(source) == sections(dest)
    assert all(symbol(source, name) == symbol(dest, name) for name in SYMBOLS)
    changed = [i for i, (a, b) in enumerate(zip(data, patched)) if a != b]
    assert changed == sorted(p['offset'] + i for p in patches for i in range(2))
    result = dict(kind='A: behaviour twin', post=str(source), post_sha256=sha(data),
                  pad_a=str(dest), pad_a_sha256=sha(patched), changed_bytes=len(changed), patches=patches)
    Path(receipt).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('post')
    ap.add_argument('pad_a')
    ap.add_argument('--receipt', required=True)
    args = ap.parse_args()
    build(args.post, args.pad_a, args.receipt)
