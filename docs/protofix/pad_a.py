#!/usr/bin/env python3
"""Exact POST-layout PAD-A: transplant the two PRE inline parser bodies.

PRE's validators occupy the now-unreachable POST decoder slots. All other text,
data, function addresses and section sizes remain byte-identical to POST. This
is an x86-64 throwaway control, not a source/build option. Relocations are bounded
to decoded instructions and checked against the original encoded displacement.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf

pre_path = ROOT / "build/protofix/pre-source/build/tomokv"
post_path = ROOT / "build/tomokv"
output = ROOT / "build/tomokv-protofix-PAD-A"
pre, post = Elf(pre_path), Elf(post_path)
old_functions, new_functions = pre.functions(), post.functions()
data = bytearray(post.data)


def offset(elf, address):
    for section in elf.sections:
        if section[1] != 8 and section[2] & 2 and section[3] <= address < section[3] + section[5]:
            return section[4] + address - section[3]
    raise AssertionError(hex(address))


def instructions(path, symbol):
    text = subprocess.check_output(["objdump", "-dw", "-Mintel", "--disassemble=" + symbol, str(path)], text=True)
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)", line)
        if m:
            rows.append((int(m[1], 16), bytes.fromhex(m[2]), m[3]))
    return rows


labels = {}
for section in (".plt", ".plt.sec", ".plt.got"):
    text = subprocess.check_output(["objdump", "-d", "-j", section, str(post_path)], text=True)
    labels.update({name: int(addr, 16) for addr, name in re.findall(r"^([0-9a-f]+) <([^>]+)>:", text, re.M)})
mapping, replacements = {}, []
for ns in ("4tomo", "8tomo_db0"):
    parser = "_ZN" + ns + "17resp_parse_inlineEPKcjRjRNS_2OpEPS1_S2_"
    validator = "_ZN" + ns + "24resp_inline_quotes_validEPKcS1_"
    unused = "_ZN" + ns + "17RespInlineDecoder5splitEPKcS2_PNS_5SliceEPcRj"
    mapping[validator] = new_functions[unused]["value"]
    replacements.extend(((parser, parser), (validator, unused)))
changes = []
for old_name, slot_name in replacements:
    old, slot = old_functions[old_name], new_functions[slot_name]
    assert old["size"] <= slot["size"], (old_name, old["size"], slot["size"])
    body = bytearray(pre.body(old))
    relocations = []
    decoded = instructions(pre_path, old_name)
    assert sum(len(raw) for _, raw, _ in decoded) == len(body)
    for address, raw, ins in decoded:
        relative = address - old["value"]
        target, destination, field = None, None, None
        branch = re.match(r"(?:call|j\w+)\s+([0-9a-f]+) <([^>]+)>", ins)
        if branch:
            target = int(branch[1], 16)
            if old["value"] <= target < old["value"] + old["size"]:
                continue
            name = branch[2]
            assert len(raw) == 5 and raw[0] in (0xe8, 0xe9), ins
            destination = mapping.get(name, labels.get(name))
            if destination is None:
                destination = new_functions[name]["value"]
            field = 1
        elif "rip" in ins:
            ref = re.search(r"# ([0-9a-f]+)", ins)
            assert ref and ins.startswith("lea"), ins
            target = int(ref[1], 16)
            at = offset(pre, target)
            literal = pre.data[at:pre.data.index(b"\0", at) + 1]
            assert literal.startswith(b"ERR "), literal
            rodata = post.sections[post.names.index(".rodata")]
            target_offset = post.section_data(post.names.index(".rodata")).index(literal)
            destination = rodata[3] + target_offset
            name = literal.decode().rstrip("\0")
            field = len(raw) - 4
        if field is not None:
            assert address + len(raw) + struct.unpack_from("<i", raw, field)[0] == target
            displacement = destination - (slot["value"] + relative + len(raw))
            struct.pack_into("<i", body, relative + field, displacement)
            relocations.append(dict(offset=relative + field, target=name, old=hex(target), new=hex(destination)))
    location = offset(post, slot["value"])
    data[location:location + slot["size"]] = body + b"\x90" * (slot["size"] - len(body))
    changes.append(dict(pre_symbol=old_name, post_slot=slot_name, address=hex(slot["value"]),
                        file_offset=location, pre_size=old["size"], slot_size=slot["size"], relocations=relocations))

# The executable is a distinct artifact; do not retain POST's build-id.
note = post.sections[post.names.index(".note.gnu.build-id")]
assert note[5] == 36
build_id_at = note[4] + 16
data[build_id_at:build_id_at + 20] = b"\0" * 20
data[build_id_at:build_id_at + 20] = hashlib.sha1(data).digest()
allowed = [(row["file_offset"], row["file_offset"] + row["slot_size"]) for row in changes] + [(build_id_at, build_id_at + 20)]
for i, (a, b) in enumerate(zip(post.data, data)):
    assert a == b or any(lo <= i < hi for lo, hi in allowed), i
assert len(data) == len(post.data)
output.write_bytes(data)
output.chmod(0o755)
pad = Elf(output)
assert pad.sections == post.sections
report = dict(kind="A: behaviour twin", behavior="PRE 83e0b809d inline parser and validator; POST elsewhere",
              matched="Every POST function address and section size; all bytes outside the four listed inline-only bodies and build-id",
              limitation="Throwaway parser slots retain POST debug/unwind metadata; do not use this arm for parser stack-unwind diagnostics.",
              changes=changes, arms={name: dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                                    for name, path in (("PRE", pre_path), ("POST", post_path), ("PAD-A", output))})
(ROOT / "docs/protofix/pad-a.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report["arms"], indent=2))
