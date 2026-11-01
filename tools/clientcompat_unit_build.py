#!/usr/bin/env python3
"""Rebuild required units in bounded disk batches, retaining ELF identity receipts."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess


DOC = Path("docs/clientcompat")
SOURCE_COMMIT = os.environ.get("CLIENTCOMPAT_SOURCE_COMMIT", "1076280569")


def allocated(data):
    assert data[:6] == b"\x7fELF\x02\x01"
    offset = struct.unpack_from("<Q", data, 40)[0]
    size, count, names = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * size)
                for i in range(count)]
    strings = data[sections[names][4]:sections[names][4] + sections[names][5]]
    return [(strings[s[0]:].split(b"\0", 1)[0], s[1], s[3], s[5],
             hashlib.sha256(data[s[4]:s[4] + s[5]] if s[1] != 8 else b"").digest())
            for s in sections if s[2] & 2]


def trim_units():
    receipt = DOC / "unit-debug-trim.json"
    records = json.loads(receipt.read_text())
    for path in sorted(Path("build").rglob("*")):
        if path.is_symlink() or not path.is_file() or "clientcompat" in path.parts:
            continue
        if path in (Path("build/tomokv"), Path("build/blockfix-cost")) or path.suffix in (".o", ".a"):
            continue
        stat = path.stat()
        if stat.st_size < 80_000_000 or not os.access(path, os.X_OK):
            continue
        before = path.read_bytes()
        if before[:4] != b"\x7fELF":
            continue
        subprocess.run(["strip", "--strip-debug", str(path)], check=True)
        after = path.read_bytes()
        assert allocated(before) == allocated(after), path
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        if before != after:
            records.append(dict(path=str(path), before_sha256=hashlib.sha256(before).hexdigest(),
                                after_sha256=hashlib.sha256(after).hexdigest(),
                                before_bytes=len(before), after_bytes=len(after),
                                allocated_sections_identical=True, trim_revision=SOURCE_COMMIT))
    receipt.write_text(json.dumps(records, indent=2) + "\n")


def finish_unit_artifacts():
    # The cost probe has an explicit server/probe binding. Older cleanup runs
    # also stripped its debug information; bind the retained, allocation-
    # identical bytes rather than leaving a stale file digest beside it.
    binding = Path("build/tomokv.blockfix-cost.sha256")
    if binding.exists():
        binding.write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " +
                                   str(p.resolve()) + "\n"
                                   for p in (Path("build/tomokv"), Path("build/blockfix-cost"))))
    for path in Path("build").iterdir():
        if not path.is_file() or path.name == "tomokv":
            continue
        if not os.access(path, os.X_OK) and path.name not in (
                "tomokv.asserts.tsv", "tomokv.blockfix-cost.sha256"):
            continue
        link = Path("build/clientcompat/POST") / path.name
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(Path("../..") / path.name)


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 80))
    os.environ["LC_ALL"] = "C"
    targets = json.loads((DOC / "production-targets.json").read_text())
    commands = [["make", "-j16", target] for target in targets]
    commands += [
        ["make", "-j16", "mdbqsbr-live-arms"],
        ["make", "-f", "Makefile", "-f", "tools/blockfix_cost.mk", "-j16", "build/blockfix-cost"],
        ["make", "-f", "Makefile", "-f", "tools/blockfix2.mk", "-j16",
         "build/blockfix2-unit", "build/blockfix2-db0-unit"],
    ]
    receipt = DOC / "production-builds.json"
    records = json.loads(receipt.read_text())
    for index, command in enumerate(commands):
        log = Path(f"build/clientcompat/ack-units-{index:02d}.log")
        with log.open("w") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
        records.append(dict(command=command, exit=result.returncode, log=str(log),
                            source_commit=SOURCE_COMMIT))
        receipt.write_text(json.dumps(records, indent=2) + "\n")
        print(index, result.returncode, command[-1], flush=True)
        assert result.returncode == 0, log
        trim_units()
    finish_unit_artifacts()


if __name__ == "__main__":
    main()
