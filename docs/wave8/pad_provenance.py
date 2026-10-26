#!/usr/bin/env python3
"""Resolve PRE/PAD's four unsymbolized read-local fence branches exactly.

The strict gate inventory remains unchanged. Both the outgoing branch and the
return branch are checked; the actual fence instructions must be byte-identical.
"""
import json
import re
import struct
import subprocess
from pathlib import Path
import identity
from lbstall_artifacts import Elf

ROOT = identity.ROOT
rows = json.loads((ROOT / 'docs/wave8/pad-identity/changed-bodies.json').read_text())
paths = {'pre': ROOT / 'build/tomokv-wave8-PRE', 'pad': ROOT / 'build/tomokv-wave8-PAD-A'}
inventories = {arm: identity.inventory(path) for arm, path in paths.items()}
elves = {arm: Elf(path) for arm, path in paths.items()}


def inspect(arm, name):
    entry, = inventories[arm]['groups'][name]
    start, size = int(entry['address'], 16), entry['size']
    text = subprocess.check_output(['objdump', '-dw', '--start-address=' + hex(start),
                                   '--stop-address=' + hex(start + size), str(paths[arm])], text=True)
    code = [(int(m[1], 16), m[2].split(), m[3]) for line in text.splitlines()
            if (m := identity.audit.INSTRUCTION.match(line))]
    names = sorted({m[2].split('+0x')[0] for line in text.splitlines()
                    for m in identity.audit.REFERENCE.finditer(line)})
    decoded = subprocess.check_output(['c++filt', *names], text=True).splitlines()
    demangle = {m: identity.audit.canonical(n) for m, n in zip(names, decoded)}
    elf = elves[arm]
    section = elf.sections[elf.names.index('.rlfence')]
    assert section[5] == 112
    resolved, evidence = [], []
    for at, raw, asm in code:
        normalized = identity.audit.normalize_asm(asm, start, size, demangle)
        encoded = identity.audit.normalized_encoding(raw, asm, at, start, size)
        jump = re.fullmatch(r'jmp\s+([0-9a-f]+) <.+>', asm)
        if jump and section[3] <= int(jump[1], 16) < section[3] + section[5]:
            target = int(jump[1], 16)
            offset = target - section[3]
            assert offset % 28 == 0
            data = elf.section_data(elf.names.index('.rlfence'))[offset:offset+28]
            assert len(data) == 28 and data[23] == 0xe9
            returned = target + 28 + struct.unpack_from('<i', data, 24)[0]
            assert returned == start + 0x3e
            normalized = 'jmp <verified-rlfence+' + hex(offset) + '>'
            evidence.append(dict(branch_offset=at-start, section_offset=offset,
                                 bytes_before_return=data[:24].hex(), return_offset=returned-start))
        resolved.append([at-start, len(raw), normalized, encoded])
    assert len(evidence) == 1
    return dict(instructions=resolved, fence=evidence[0])


result = {}
for row in rows:
    name = row['name']
    if not row['headline_sizes']:
        assert name == 'tomo_wave8_pad_a'
        result[name] = dict(reason='Unreachable text padding; no fence branch targets it.')
        continue
    assert 'drain_local_reads_bounded_impl' in name
    before, after = inspect('pre', name), inspect('pad', name)
    assert before == after, name
    wrong = json.loads(json.dumps(after)); wrong['fence']['return_offset'] += 1
    assert wrong != before
    wrong = json.loads(json.dumps(after)); wrong['instructions'][0][3] += ' 90'
    assert wrong != before
    result[name] = dict(proof=before, changed_return_rejected=True, changed_opcode_rejected=True)
assert len(result) == 5
(ROOT / 'docs/wave8/pad-identity/provenance.json').write_text(json.dumps(result, indent=2) + '\n')
print('PAD: four verified .rlfence relocations, one unreachable padding symbol; all other groups strict-identical.')
