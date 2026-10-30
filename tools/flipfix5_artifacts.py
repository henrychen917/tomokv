#!/usr/bin/env python3
"""flipfix5 PAD-A: PRE behaviour in POST's exact ELF layout. No server, no load generator.

POST adds one out-of-line Server::flip_stage_owed() per database namespace. PAD-A keeps every
POST byte except two two-byte branches in each copy, which restore the pre-flipfix5 test
(!flip_acked(tid, stage), i.e. the acknowledgement token against the live epoch):

  je  <live>     after the stage reload compare  ->  jmp <live>   (74 rr -> eb rr)
  jne <stale>    after the epoch reload compare  ->  2-byte nop    (75 rr -> 66 90)

The patched function loads the epoch once, then returns token != (epoch << 8 | stage); its
stale-sample path (and the refusal counter) becomes unreachable. Plans are derived from the
disassembly, asserted instruction by instruction, written before mutation, and re-verified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from rlfence_artifacts import instructions

SYMBOLS = ('_ZNK4tomo6Server15flip_stage_owedEjNS_9FlipStageE',
           '_ZNK8tomo_db06Server15flip_stage_owedEjNS_9FlipStageE')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sections(path):
    """name -> (vma, file offset, size) for allocated sections, from readelf -SW."""
    out = {}
    for line in subprocess.check_output(['readelf', '-SW', str(path)], text=True).splitlines():
        m = re.match(r'\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)', line)
        if m:
            out[m[1]] = (int(m[2], 16), int(m[3], 16), int(m[4], 16))
    return out


def symbol(path, name):
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(path)], text=True).splitlines():
        words = line.split()
        if len(words) == 4 and words[3] == name:
            return int(words[0], 16), int(words[1], 16)
    raise AssertionError(f'{name} missing from {path}')


def function_rows(path, name):
    start, size = symbol(path, name)
    text = subprocess.check_output(['objdump', '-dw', f'--start-address={start:#x}',
                                    f'--stop-address={start + size:#x}', str(path)], text=True)
    return start, size, [(pc, raw, asm) for pc, raw, asm, _ in instructions(text)]


def plan(path):
    text_vma, text_off, text_size = sections(path)['.text']
    patches = []
    for name in SYMBOLS:
        start, size, rows = function_rows(path, name)
        branches = [(i, pc, raw, asm) for i, (pc, raw, asm) in enumerate(rows)
                    if re.match(r'j(?!mp)[a-z]+\s', asm)]
        assert len(branches) == 3, (name, branches)
        # 1: the stage reload compare branches to the epoch reload when equal.
        i, pc, raw, asm = branches[0]
        assert rows[i - 1][2].startswith('cmp') and raw[0] == 0x74 and len(raw) == 2, (name, rows[i - 1:i + 1])
        live = pc + 2 + int.from_bytes(raw[1:], 'little', signed=True)
        stale = pc + 2
        # 3: the epoch reload compare, inside the live block, branches back to the stale path.
        j, pc2, raw2, asm2 = branches[2]
        assert raw2[0] == 0x75 and len(raw2) == 2 and \
            pc2 + 2 + int.from_bytes(raw2[1:], 'little', signed=True) == stale, (name, asm2)
        assert rows[j - 1][2].startswith('cmp') and rows[j - 2][0] == live, (name, rows[j - 2:j + 1])
        # 2: the stale path's PRE-would-act branch to the counter (lock incl); left untouched.
        k, pc3, raw3, asm3 = branches[1]
        target3 = pc3 + 2 + int.from_bytes(raw3[1:], 'little', signed=True)
        assert any(p == target3 and a.startswith('lock inc') for p, _, a in rows), (name, asm3)
        assert start <= stale < live < pc2 < start + size
        for at, before, after, purpose in ((pc, raw, bytes.fromhex('eb') + raw[1:],
                                            'PRE: take the live branch unconditionally'),
                                           (pc2, raw2, bytes.fromhex('6690'),
                                            'PRE: ignore an epoch change across the stage reload')):
            patches.append(dict(symbol=name, address=at, offset=text_off + at - text_vma,
                                before=before.hex(), after=after.hex(), purpose=purpose))
    return dict(kind='A: behaviour twin', source_sha256=sha(Path(path).read_bytes()), patches=patches)


def apply(source, dest, out):
    data = bytearray(Path(source).read_bytes())
    p = plan(source)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(p, indent=2) + '\n')
    for patch in p['patches']:
        at, before, after = patch['offset'], bytes.fromhex(patch['before']), bytes.fromhex(patch['after'])
        assert data[at:at + len(before)] == before, patch
        data[at:at + len(after)] = after
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(bytes(data))
    Path(dest).chmod(0o755)
    verify(source, dest, out)


def verify(source, dest, out):
    p = json.loads(Path(out).read_text())
    a, b = Path(source).read_bytes(), Path(dest).read_bytes()
    assert len(a) == len(b) and sha(a) == p['source_sha256']
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    expected = sorted(patch['offset'] + i for patch in p['patches']
                      for i in range(len(patch['before'])//2) if
                      bytes.fromhex(patch['before'])[i] != bytes.fromhex(patch['after'])[i])
    assert changed == expected, (changed, expected)
    assert sections(source) == sections(dest)
    for name in SYMBOLS:
        assert symbol(source, name) == symbol(dest, name)
        _, _, rows = function_rows(dest, name)
        asm = [r[2] for r in rows]
        assert any(x.startswith('jmp') for x in asm) and sum(x.startswith('xchg   %ax,%ax') or
                                                             x == 'xchg   %ax,%ax' for x in asm) >= 1, asm
    summary = dict(pad_a=str(dest), pad_a_sha256=sha(b), post=str(source), post_sha256=sha(a),
                   changed_bytes=len(changed), patches=len(p['patches']))
    print(json.dumps(summary))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('post')
    ap.add_argument('pad_a')
    ap.add_argument('--plan', required=True)
    args = ap.parse_args()
    apply(args.post, args.pad_a, args.plan)


if __name__ == '__main__':
    main()
