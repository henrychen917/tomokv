#!/usr/bin/env python3
"""Make the multidb kind-A PAD without relinking or running the executable."""
import argparse
import hashlib
import json
from pathlib import Path
from lbstall_artifacts import Elf


def twin(source, output):
    elf = Elf(source)
    assert elf.kind != 1 and Path(source).resolve() != Path(output).resolve()
    matches = [symbol for symbol in elf.functions().values()
               if "multidb_namespace" in symbol["name"] and ".cold" not in symbol["name"]]
    assert len(matches) == 1, "namespace helper must have exactly one out-of-line body"
    symbol = matches[0]
    section = elf.sections[symbol["sec"]]
    start = section[4] + symbol["value"] - section[3]
    offset = start
    data = bytearray(elf.data)
    if data[offset:offset + 4] == b"\xf3\x0f\x1e\xfa":
        offset += 4
    assert offset + 3 <= start + symbol["size"]
    data[offset:offset + 3] = b"\x31\xc0\xc3"  # xor eax,eax; ret: namespace forced to DB 0
    assert len(data) == len(elf.data)
    assert data[:offset] == elf.data[:offset] and data[offset + 3:] == elf.data[offset + 3:]
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    twin_elf = Elf(output)
    assert twin_elf.sections == elf.sections and twin_elf.symbols == elf.symbols
    return dict(kind="A: behaviour twin", source=str(source), output=str(output),
                control="namespace helper always returns physical DB 0",
                symbol=symbol["name"], file_offset=offset,
                unchanged="all ELF section sizes, symbol addresses, and bytes outside patch",
                source_sha256=hashlib.sha256(elf.data).hexdigest(),
                pad_sha256=hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    print(json.dumps(twin(args.source, args.output), indent=2))
