#!/usr/bin/env python3
"""PAD(A): part-1 text/data layout, PRE cleanup behavior, in a disposable ELF copy.

Replace only the two out-of-line registration entries with `return true`. IO already
stamped the Op before calling; the stub neither advances that cut nor takes a reference.
With --hold, replace plain_hold_begin with `return cut` instead: no bucket is
acquired, and the caller's zero bucket makes its end commit a no-op. No production
object or source is changed. The negative hunt must fail on either arm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--part1", type=Path, default=root / "build/tornread/tomokv-part1-r7")
parser.add_argument("--hold", type=Path, help="hold candidate instead of the per-read PART1 arm")
parser.add_argument("--output", type=Path, default=root / "build/tornread/tomokv-pad1-r7")
args = parser.parse_args()
source, target = args.hold or args.part1, args.output
symbol = "plain_hold_begin" if args.hold else "register_plain_read"
stub = bytes.fromhex("4889c8c3" if args.hold else "b801000000c3")
data = source.read_bytes()
assert data[:6] == b"\x7fELF\x02\x01"
assert struct.unpack_from("<H", data, 18)[0] == 62  # x86-64
phoff = struct.unpack_from("<Q", data, 32)[0]
phsize, phnum = struct.unpack_from("<HH", data, 54)
segments = [struct.unpack_from("<IIQQQQQQ", data, phoff + n * phsize) for n in range(phnum)]
symbols = subprocess.check_output(["nm", "-S", "--defined-only", "-C", str(source)], text=True)
patches = []
for line in symbols.splitlines():
    if f"::ScatterArenaPool::{symbol}(" not in line or "[clone" in line:
        continue
    address, size, kind, name = line.split(maxsplit=3)
    address, size = int(address, 16), int(size, 16)
    assert kind == "T" and size >= len(stub)
    segment = next(s for s in segments if s[0] == 1 and s[3] <= address < s[3] + s[5])
    offset = segment[2] + address - segment[3]
    patches.append(dict(symbol=name, offset=offset, before=data[offset:offset + len(stub)].hex(),
                        after=stub.hex()))
assert len(patches) == 2
shutil.copy2(source, target)
with target.open("r+b") as binary:
    for patch in patches:
        binary.seek(patch["offset"])
        binary.write(bytes.fromhex(patch["after"]))
changed = target.read_bytes()
allowed = {patch["offset"] + i for patch in patches for i in range(len(stub))}
assert len(data) == len(changed)
assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(data, changed)))
record = dict(kind="A: behaviour twin", source=str(source), target=str(target), patches=patches,
              source_sha256=hashlib.sha256(data).hexdigest(),
              target_sha256=hashlib.sha256(changed).hexdigest())
(target.parent / (target.name.removeprefix("tomokv-") + ".json")).write_text(
    json.dumps(record, indent=2) + "\n")
print(target)
