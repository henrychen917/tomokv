"""Independently verify all four strict PAD-A trampoline residuals."""
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

pre, pad = Elf(ROOT / 'build/tomokv-PRE'), Elf(ROOT / 'build/tomokv-PAD-A')


def section(elf, name):
    index = elf.names.index(name)
    return elf.sections[index][3], elf.section_data(index)


def read(elf, address, size):
    for index, sec in enumerate(elf.sections):
        if sec[1] != 8 and sec[3] <= address and address + size <= sec[3] + sec[5]:
            return elf.section_data(index)[address-sec[3]:address-sec[3]+size]
    raise AssertionError(hex(address))


def functions(elf):
    return sorted((sym['name'], sym['value'], sym['size']) for sym in elf.symbols
                  if sym['info'] & 15 == 2 and sym['sec'] == elf.names.index('.text'))


assert functions(pre) == functions(pad)
gap = json.loads((ROOT / 'docs/trackfix/pad.json').read_text())['padding_bytes']
text0, text1 = section(pre, '.text'), section(pad, '.text')
assert text0[0] == text1[0] and len(text1[1]) - len(text0[1]) == gap
assert text1[1][len(text0[1]):] == bytes([0x90]) * gap
tr0, tr1 = section(pre, '.rlfence'), section(pad, '.rlfence')
assert tr1[0] - tr0[0] == gap and len(tr0[1]) == len(tr1[1]) == 112
assert section(pre, '.note.gnu.property')[1] == section(pad, '.note.gnu.property')[1]
rows = {}
for name, address, size in functions(pre):
    if 'drain_local_reads_bounded_impl' not in name or size != 328:
        continue
    left, right = read(pre, address + 0x39, 5), read(pad, address + 0x39, 5)
    assert left[0] == right[0] == 0xe9
    dst0 = address + 0x3e + struct.unpack_from('<i', left, 1)[0]
    dst1 = address + 0x3e + struct.unpack_from('<i', right, 1)[0]
    offset = dst0 - tr0[0]
    assert offset == dst1 - tr1[0] and offset in (0, 28, 56, 84)
    body0, body1 = tr0[1][offset:offset+28], tr1[1][offset:offset+28]
    assert body0[:24] == body1[:24] and body0[23] == 0xe9
    assert (dst0 + 28 + struct.unpack_from('<i', body0, 24)[0] ==
            dst1 + 28 + struct.unpack_from('<i', body1, 24)[0] == address + 0x3e)
    # GCC exposes two aliases per body; both aliases were checked above.
    row = rows.setdefault(address, dict(aliases=[], entry=hex(address), offset=offset,
                                       return_to=hex(address + 0x3e)))
    row['aliases'].append(name)
assert len(rows) == 4 and all(len(row['aliases']) == 2 for row in rows.values())
result = dict(status='PASS', strict_residuals=4, padding_bytes=gap,
              all_pre_text_function_addresses_and_sizes_equal=True,
              gnu_properties_equal=True, trampolines=list(rows.values()))
(ROOT / 'docs/trackfix/identity/pad-relocations.json').write_text(json.dumps(result, indent=2) + '\n')
print('PAD-A: four trampoline entries and return targets verified; eight symbol aliases')
