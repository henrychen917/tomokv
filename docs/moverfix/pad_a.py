#!/usr/bin/env python3
"""PAD-A: retain every POST ELF address; restore PRE mover decisions in a COPY.

The claim helper keeps its POST footprint and guards. Branch/call/store patches
restore phase-one guesses, independent destinations, old SMOVE success and the
old pop read context. No production source or production binary is modified.
Every patch is instruction-boundary checked and logged with before/after bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from lbstall_artifacts import Elf

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("source", type=Path)
p.add_argument("output", type=Path)
p.add_argument("receipt", type=Path)
a = p.parse_args()
assert a.source.resolve() != a.output.resolve()
elf = Elf(a.source)
image = bytearray(elf.data)
patches = []

def instructions(symbol):
    raw = subprocess.check_output(["objdump", "-dw", "--disassemble=" + symbol["name"], str(a.source)], text=True)
    rows = []
    for line in raw.splitlines():
        m = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*([^\s].*)", line)
        if m:
            rows.append((int(m[1], 16), bytes.fromhex(m[2]), m[3]))
    assert rows and rows[0][0] == symbol["value"]
    return rows

def edit(symbol, insn, replacement, reason):
    address, before, decoded = insn
    assert len(before) == len(replacement)
    section = elf.sections[symbol["sec"]]
    offset = section[4] + address - section[3]
    assert image[offset:offset + len(before)] == before
    image[offset:offset + len(before)] = replacement
    patches.append(dict(symbol=symbol["name"], offset=address-symbol["value"],
                        file_offset=offset, before=before.hex(), after=replacement.hex(),
                        decoded=decoded, reason=reason))

def nop(symbol, insn, reason):
    edit(symbol, insn, b"\x90" * len(insn[1]), reason)

def unique(rows, predicate):
    matched = [r for r in rows if predicate(r[2])]
    assert len(matched) == 1, matched
    return matched[0]

movers = [s for s in elf.functions().values() if "execute_plain_element_mover" in s["name"] and ".cold" not in s["name"]]
pops = [s for s in elf.functions().values() if "execute_live_pop" in s["name"] and ".cold" not in s["name"]]
assert len(movers) == len(pops) == 2
for symbol in movers:
    rows = instructions(symbol)
    for pattern, reason in [
        (r"cmpl\s+\$0x1,\(", "destination may execute before source"),
        (r"cmpb\s+\$0x0,0x3c\(", "retain PRE probe read context"),
        (r"cmp\s+\$0x1,%eax$", "destination ignores source claim status")]:
        compare = unique(rows[:80], lambda s: re.search(pattern, s))
        branch = rows[rows.index(compare) + 1]
        assert branch[2].startswith("je "), branch
        nop(symbol, branch, reason)
    peek = unique(rows, lambda s: s.startswith("call ") and "xshard_peek_list" in s)
    assert len(peek[1]) == 5
    edit(symbol, peek, b"\x31\xc0\x90\x90\x90", "remove phase-one guess; do not refresh it")
    nop(symbol, unique(rows, lambda s: re.match(r"mov\s+%al,0x1e\(", s)),
        "leave direct_ready zero so PRE still returns its phase-one guess on a miss")
    nop(symbol, unique(rows, lambda s: re.match(r"mov\s+%\w+,0x128\(", s)),
        "retain phase-one SMOVE success instead of actual-removal success")
for symbol in pops:
    rows = instructions(symbol)
    branch = next(r for r in rows if r[2].startswith("jne "))
    target = int(branch[2].split()[1], 16)
    assert target > branch[0] and target - branch[0] < 64
    if len(branch[1]) == 2:
        replacement = b"\xeb" + branch[1][1:]
    else:
        assert len(branch[1]) == 6
        replacement = b"\xe9" + struct.pack("<i", target - branch[0] - 5) + b"\x90"
    edit(symbol, branch, replacement, "skip live read-context binding; retain PRE pop context")
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_bytes(image)
a.output.chmod(0o755)
patched = Elf(a.output)
assert elf.sections == patched.sections
assert elf.symbols == patched.symbols
receipt = dict(kind="A: behaviour twin", post_sha256=hashlib.sha256(elf.data).hexdigest(),
               pad_sha256=hashlib.sha256(image).hexdigest(), all_section_headers_equal=True,
               all_symbol_addresses_and_sizes_equal=True, patches=patches)
a.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
print(receipt["pad_sha256"], "patches", len(patches))
