#!/usr/bin/env python3
"""PAD(A): part-1 text/data layout, PRE cleanup behavior, in a disposable ELF copy.

Replace only the two out-of-line registration entries with `return true`. IO already
stamped the Op before calling; the stub neither advances that cut nor takes a reference.
No production object or source is changed. The negative hunt must fail on this arm.
"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
source = root / "build/tornread/tomokv-part1"
target = root / "build/tornread/tomokv-pad1"
data = source.read_bytes()
assert data[:6] == b"\x7fELF\x02\x01"
assert struct.unpack_from("<H", data, 18)[0] == 62  # x86-64
phoff = struct.unpack_from("<Q", data, 32)[0]
phsize, phnum = struct.unpack_from("<HH", data, 54)
segments = [struct.unpack_from("<IIQQQQQQ", data, phoff + n * phsize) for n in range(phnum)]
symbols = subprocess.check_output(["nm", "-S", "--defined-only", "-C", str(source)], text=True)
patches = []
for line in symbols.splitlines():
    if "::ScatterArenaPool::register_plain_read(" not in line or "[clone" in line:
        continue
    address, size, kind, name = line.split(maxsplit=3)
    address, size = int(address, 16), int(size, 16)
    assert kind == "T" and size >= 6
    segment = next(s for s in segments if s[0] == 1 and s[3] <= address < s[3] + s[5])
    offset = segment[2] + address - segment[3]
    patches.append(dict(symbol=name, offset=offset, before=data[offset:offset + 6].hex(),
                        after="b801000000c3"))
assert len(patches) == 2
shutil.copy2(source, target)
with target.open("r+b") as binary:
    for patch in patches:
        binary.seek(patch["offset"])
        binary.write(bytes.fromhex(patch["after"]))
changed = target.read_bytes()
allowed = {patch["offset"] + i for patch in patches for i in range(6)}
assert len(data) == len(changed)
assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(data, changed)))
record = dict(kind="A: behaviour twin", source=str(source), target=str(target), patches=patches,
              source_sha256=hashlib.sha256(data).hexdigest(),
              target_sha256=hashlib.sha256(changed).hexdigest())
(target.parent / "pad1.json").write_text(json.dumps(record, indent=2) + "\n")
print(target)
