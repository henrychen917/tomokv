#!/usr/bin/env python3
"""Verify the one anonymous Lua literal missed by the strict body normalizer."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from wave15 import BUILD, DOC, save


def literal(arm, path):
    data = path.read_bytes()
    nm = subprocess.check_output(['nm', '-S', '--defined-only', str(path)], text=True)
    line = next(line for line in nm.splitlines() if line.endswith(' luaV_execute'))
    start = int(line.split()[0], 16)
    dis = subprocess.check_output(['objdump', '-d', '-w', '--start-address='+hex(start+0x2fc),
        '--stop-address='+hex(start+0x304), str(path)], text=True)
    matches = re.findall(r'vxorpd\s+(-?0x[0-9a-f]+)\(%rip\),%xmm0,%xmm0\s+#\s+([0-9a-f]+)', dis)
    assert len(matches) == 1, dis
    displacement, target = matches[0]
    target = int(target, 16)
    assert start+0x304+int(displacement, 16) == target
    table = struct.unpack_from('<Q', data, 40)[0]
    width, count, _ = struct.unpack_from('<HHH', data, 58)
    value = None
    for i in range(count):
        h = struct.unpack_from('<IIQQQQIIQQ', data, table+i*width)
        if h[1] == 1 and h[2] & 2 and not h[2] & (1 | 4) and h[3] <= target and target+16 <= h[3]+h[5]:
            value = data[h[4]+target-h[3]:h[4]+target-h[3]+16]
    assert value is not None
    for line in nm.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[2] not in 'tTwW':
            at, size = int(parts[0], 16), int(parts[1], 16)
            assert not (size and at < target+16 and target < at+size), (line, target)
    return dict(arm=arm, path=str(path), sha256=hashlib.sha256(data).hexdigest(), instruction=dis.strip(),
        function_address=hex(start), literal_address=hex(target), literal=value.hex())


if __name__ == '__main__':
    rows = [literal('server', BUILD/'POST-1babe0d58a-final')]
    for kind in ('scripts', 'tracked-scripts'):
        meta = json.loads((DOC/'instructions'/('post-'+kind+'-final')/'normal-build.json').read_text())
        rows.append(literal(kind, Path(meta['link'][meta['link'].index('-o')+1])))
    assert len({row['literal'] for row in rows}) == 1
    record = json.loads((DOC/'lua-binding.json').read_text())
    assert record['encodings_equal']
    # The retained complete normalized diff must contain exactly this one
    # instruction substitution; no other instruction is exempted.
    changed = [s for s in record['instruction_diff'] if s.startswith(('-', '+')) and not s.startswith(('---', '+++'))]
    assert len(changed) == 2 and all('02fc [ 8] vxorpd ' in s for s in changed)
    record['literal_reads'] = rows
    record['resolution'] = ('The sole normalized-assembly difference is the nearest-symbol label of an anonymous '
        '128-bit VXORPD literal. Opcode/register/branch encodings match, RIP targets are checked, and all 16 '
        'consumed bytes match. Named, writable and executable objects are excluded.')
    save(DOC/'lua-binding.json', record)
    print('Verified both Lua probe literal loads:', rows[0]['literal'])
