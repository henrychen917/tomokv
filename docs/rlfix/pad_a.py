#!/usr/bin/env python3
"""Offline PAD-A builder: PRE miss/delete behavior at POST's exact text layout."""
import argparse
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

POST_SHA = "d3880ba6d766c80b0b296c5eb99590d8c25b0f02a32aeefdf234ca55077a97a6"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("receipt", type=Path)
    a = p.parse_args()
    assert a.source.resolve() != a.output.resolve()
    elf = Elf(a.source)
    assert elf.kind != 1
    assert hashlib.sha256(elf.data).hexdigest() == POST_SHA, "re-audit a changed POST"
    data = bytearray(elf.data)
    patches = []
    for symbol in elf.functions().values():
        name = symbol["name"]
        if ".cold" in name:
            continue
        body = elf.body(symbol)
        if "18prepare_local_read" in name:
            assert symbol["size"] == 2249
            # Missing's taken edge; all hit-path bytes stay exactly POST's.
            assert body[0x93:0x97] == bytes.fromhex("3c 01 0f 84")
            assert 0x9b + struct.unpack_from("<i", body, 0x97)[0] == 0x160
            # Reuse the existing clear-reply + Typed aggregate construction.
            # Change only its reason to Missing and jump to the same canary-
            # checked epilogue. No FlatStore access, notification or nil reply.
            replacement = bytearray(body[0xc7:0x117])
            assert replacement[:10] == bytes.fromhex("48 b8 00 00 00 00 ff ff ff ff")
            assert replacement[-20:] == bytes.fromhex(
                "c6 84 24 90 00 00 00 0b 48 c7 84 24 94 00 00 00 00 00 00 00")
            replacement[-13] = 10  # ReadLocalFallbackReason::Missing
            at = 0x160
            replacement += b"\xe9" + struct.pack("<i", 0x120 - (at + len(replacement) + 5))
            # No edge from outside this patch may enter its interior.
            asm = subprocess.check_output([
                "objdump", "-dw", "--start-address=" + str(symbol["value"]),
                "--stop-address=" + str(symbol["value"] + symbol["size"]),
                str(a.source)], text=True)
            for m in re.finditer(r"^\s*([0-9a-f]+):.*?\bj\w+\s+([0-9a-f]+)\s+<", asm, re.M):
                source, target = (int(v, 16) - symbol["value"] for v in m.groups())
                assert not (at < target < at + len(replacement) and
                            not at <= source < at + len(replacement))
            purpose = "Missing returns the PRE fallback after clearing the reply"
        elif "21ReadLocalDemotionPlan7prepare" in name:
            db0 = "tomo_db0" in name
            at, target = (0xe0, 0x180) if db0 else (0xe6, 0x190)
            assert body[at-4:at] == bytes.fromhex("41 80 fb 07" if db0 else "41 80 f8 07")
            assert body[at:at+2] == b"\x0f\x85"
            assert at + 6 + struct.unpack_from("<i", body, at+2)[0] == target
            # Unconditionally take the existing reason!=InflightWrite edge,
            # bypassing only the new point-delete classification.
            replacement = b"\xe9" + struct.pack("<i", target - at - 5) + b"\x90"
            purpose = "Skip the new DEL/UNLINK refinement; keep staged broad generation"
        else:
            continue
        section = elf.sections[symbol["sec"]]
        offset = section[4] + symbol["value"] - section[3] + at
        before = bytes(data[offset:offset+len(replacement)])
        data[offset:offset+len(replacement)] = replacement
        patches.append(dict(symbol=name, function_offset=at, file_offset=offset,
                            before=before.hex(), after=replacement.hex(), purpose=purpose))
    assert len(patches) == 4, "both mechanisms in both namespaces"
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)
    a.output.chmod(0o755)
    twin = Elf(a.output)
    assert elf.sections == twin.sections and elf.symbols == twin.symbols
    assert len(elf.data) == len(twin.data)
    for i, section in enumerate(elf.names):
        if section != ".text":
            assert elf.section_data(i) == twin.section_data(i), section
    result = dict(kind="A: behaviour twin", source=str(a.source), output=str(a.output),
                  post_sha256=POST_SHA, pad_sha256=hashlib.sha256(data).hexdigest(),
                  sections_symbols_and_sizes_identical=True,
                  changes_confined_to_four_text_ranges=True, patches=patches)
    a.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(result["pad_sha256"], a.output)


if __name__ == "__main__":
    main()
