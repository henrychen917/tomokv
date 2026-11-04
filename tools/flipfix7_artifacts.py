#!/usr/bin/env python3
"""PAD-A: PRE FLIP liveness decisions with POST's exact text size and layout.

Patch only the cold selector's mov immediate in each namespace. All output
holds, stationary-client exceptions, refusal counters, deferred releases and
blocking-publication guards then select their PRE behavior. No runtime knob.
"""
import argparse
import json
from pathlib import Path
from flipfix5_artifacts import sections, symbol, function_rows, sha

SYMBOLS = ('_ZN4tomo21flip_liveness_enabledEv', '_ZN8tomo_db021flip_liveness_enabledEv')


def build(source, dest, receipt):
    data = Path(source).read_bytes()
    patched = bytearray(data)
    text_vma, text_off, _ = sections(source)['.text']
    patches = []
    for name in SYMBOLS:
        start, size, rows = function_rows(source, name)
        found = [(pc, raw, asm) for pc, raw, asm in rows if raw == bytes.fromhex('b801000000')]
        assert len(found) == 1, (name, rows)
        pc, raw, asm = found[0]
        offset = text_off + pc - text_vma + 1
        assert data[offset] == 1
        patched[offset] = 0
        patches.append(dict(symbol=name, address=pc + 1, offset=offset, before='01', after='00'))
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(patched); dest.chmod(0o755)
    assert len(data) == len(patched) and sections(source) == sections(dest)
    assert all(symbol(source, name) == symbol(dest, name) for name in SYMBOLS)
    changed = [i for i, (a, b) in enumerate(zip(data, patched)) if a != b]
    assert changed == sorted(p['offset'] for p in patches)
    result = dict(kind='A: behaviour twin', post=str(source), post_sha256=sha(data),
                  pad_a=str(dest), pad_a_sha256=sha(patched), changed_bytes=len(changed), patches=patches)
    Path(receipt).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('post'); ap.add_argument('pad_a'); ap.add_argument('--receipt', required=True)
    args = ap.parse_args()
    build(args.post, args.pad_a, args.receipt)
