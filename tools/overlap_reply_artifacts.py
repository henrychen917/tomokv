#!/usr/bin/env python3
"""Make O7's exact-layout kind-A PAD without executing the input ELF."""
import argparse
import hashlib
import json
from pathlib import Path

from lbstall_artifacts import Elf


def twin(source, output):
    source, output = Path(source), Path(output)
    assert source.resolve() != output.resolve(), "patch a separate copy"
    elf = Elf(source)
    assert elf.kind in (2, 3), "expected a linked ELF executable"
    matches = [s for name, s in elf.functions().items() if "overlap_reply_policy" in name]
    assert len(matches) == 1, "expected one noipa policy body, without clones"
    symbol = matches[0]
    section = elf.sections[symbol["sec"]]
    offset = section[4] + symbol["value"] - section[3]
    body = elf.body(symbol)
    if body.startswith(b"\xf3\x0f\x1e\xfa"):
        offset += 4  # retain a CET landing pad
        body = body[4:]
    assert body.startswith(b"\xb8\x01\x00\x00\x00\xc3"), "expected bool true; ret on x86-64"
    patched = bytearray(elf.data)
    patched[offset:offset + 3] = b"\x31\xc0\xc3"  # bool false; ret
    assert patched[:offset] == elf.data[:offset]
    assert patched[offset + 3:] == elf.data[offset + 3:]
    output.write_bytes(patched)
    output.chmod(source.stat().st_mode)
    control = Elf(output)
    assert control.sections == elf.sections and control.symbols == elf.symbols
    return {
        "kind": "A: PRE reply scheduling with POST ELF text size/layout",
        "source": str(source), "pad": str(output),
        "file_bytes": len(patched), "text_bytes": elf.sections[elf.names.index(".text")][5],
        "policy_symbol": symbol["name"], "patch_offset": offset,
        "original_bytes": body[:3].hex(), "pad_bytes": "31c0c3",
        "post_sha256": hashlib.sha256(elf.data).hexdigest(),
        "pad_sha256": hashlib.sha256(patched).hexdigest(),
        "all_other_bytes_equal": True,
        "retained_mechanisms": "L1, O1, O6, L4, client-LB fix, retired reorder, flipctl floor",
        "identity": "Use sha256: the copied GNU build-id is intentionally unchanged.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = twin(args.source, args.output)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
