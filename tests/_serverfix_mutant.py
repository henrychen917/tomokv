"""Checked x86-64 ELF fault control; alters only throwaway executable copies."""
import hashlib
import re
import struct
import subprocess


def zero_hll_count(source, destination, oracle=False):
    data = bytearray(source.read_bytes())
    assert data[:6] == b'\x7fELF\x02\x01'
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, number = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * size) for i in range(number)]
    patches = []
    for line in subprocess.check_output(['nm', '-SC', str(source)], text=True).splitlines():
        match = re.fullmatch(r'([0-9a-f]+) ([0-9a-f]+) [TtWw] (.*)', line)
        if not match:
            continue
        name = match[3]
        wanted = name == 'hllCount' if oracle else bool(re.fullmatch(r'tomo(?:_db0)?::hll::count\(.*', name))
        if not wanted:
            continue
        address = int(match[1], 16)
        assert int(match[2], 16) >= 8
        offsets = [p[2] + address - p[3] for p in loads if p[0] == 1 and p[3] <= address < p[3] + p[5]]
        assert len(offsets) == 1
        offset = offsets[0]
        if data[offset:offset + 4] == bytes.fromhex('f30f1efa'):
            offset += 4
        before = data[offset:offset + 3].hex()
        data[offset:offset + 3] = bytes.fromhex('31c0c3')  # return uint64_t(0)
        patches.append(dict(symbol=name, address=address, offset=offset, before=before, after='31c0c3'))
    assert len(patches) == (1 if oracle else 2), patches
    destination.write_bytes(data)
    destination.chmod(0o755)
    return dict(sha256=hashlib.sha256(data).hexdigest(), patches=patches)
