#!/usr/bin/env python3
"""Type-A encodingfix control: PRE's intset default in POST's exact text/layout.

Patch only the last int64 in the emitted EncodingConfig default constant. This
keeps every executable byte, symbol, section, offset and public object layout.
The control has PRE collection behavior at default settings; the new CONFIG
surface remains present. It is an offline measurement artifact, never production.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("proof", type=Path)
    parser.add_argument("--unit", action="store_true", help="patch the matching serverless witness")
    args = parser.parse_args()
    assert args.source.resolve() != args.output.resolve()
    elf = Elf(args.source)
    needle = struct.pack("<8q", 512, 64, -2, 128, 64, 128, 64, 512)
    matches = []
    for i, name in enumerate(elf.names):
        if not name.startswith(".rodata"): continue
        section = elf.sections[i]
        data = elf.section_data(i)
        at = data.find(needle)
        while at >= 0:
            matches.append((section[4] + at, section[3] + at))
            at = data.find(needle, at + 1)
    assert 1 <= len(matches) <= 2, "expected at most one default table per namespace"
    witnessed = []
    consumed = set()
    destination = 0x160
    if args.unit:
        program = "import gdb; print(next(f.bitpos//8 for f in gdb.lookup_type('tomo::Server').fields() if f.name=='cfg_'))"
        destination += int(subprocess.check_output([
            "gdb", "-nx", "-batch", "-iex", "set debuginfod enabled off", str(args.source),
            "-ex", "python " + program], text=True).strip())
    for name, symbol in elf.functions().items():
        pattern = r"_ZN4tomo16NetcmdRegressionC2Ej" if args.unit else r"_ZN(?:4tomo|8tomo_db0)6ConfigC2Ev"
        if not re.fullmatch(pattern, name): continue
        dump = subprocess.check_output([
            "objdump", "-d", "--no-show-raw-insn", "--start-address=" + str(symbol["value"]),
            "--stop-address=" + str(symbol["value"] + symbol["size"]), str(args.source)], text=True)
        selected = [address for _, address in matches if re.search(
            r"vmovdqa64\s+.*#\s+" + f"{address:x}" + r"\s", dump)]
        assert len(selected) == 1, name
        consumed.update(selected)
        assert re.search(r"vmovdqu64\s+%zmm\d+,0x" + f"{destination:x}" + r"\(%r\w+\)", dump), name
        witnessed.append(name)
    assert witnessed, "no Config constructor consumed the default table"
    assert consumed == {address for _, address in matches}, "unwitnessed constant copy"
    data = bytearray(elf.data)
    for file_at, _ in matches:
        data[file_at + 56:file_at + 64] = struct.pack("<q", 128)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.chmod(args.source.stat().st_mode)
    pad = Elf(args.output)
    assert elf.sections == pad.sections and elf.symbols == pad.symbols
    text_bytes = 0
    for i, section in enumerate(elf.sections):
        if section[2] & 4:
            assert elf.section_data(i) == pad.section_data(i)
            text_bytes += section[5]
    changed = sorted(at + byte for at, _ in matches for byte in (56, 57))
    assert [i for i, (a, b) in enumerate(zip(elf.data, pad.data)) if a != b] == changed
    proof = dict(kind="A: behavior twin for default-threshold collection workloads",
                 source=str(args.source), output=str(args.output), constructors=witnessed,
                 constant_virtual_addresses=[hex(address) for _, address in matches],
                 intset_default_post=512, intset_default_pad=128,
                 changed_file_bytes=changed, executable_bytes_identical=text_bytes,
                 source_sha256=hashlib.sha256(elf.data).hexdigest(), pad_sha256=hashlib.sha256(pad.data).hexdigest())
    args.proof.write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__": main()
