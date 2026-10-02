#!/usr/bin/env python3
"""Serverless removal inventory, raw ELF controls, and a same-layout kind-A PAD.

Capture/compare arms with tools/ttlstate_proof.py, the existing unnormalized byte,
allocated-data, relocation-target, address and entry-point checker. This driver
only specializes the source inventory and its throwaway controls. No ELF is run.
"""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

from ttlstate_proof import Elf, capture, compare_files, save


MARKER = "note_" + "pending"
PATTERN = re.compile(r"\b" + MARKER + r"\b")
PRE_COUNTS = {"src/core/io_loop.h": 6, "src/core/reorder.cc": 1,
              "src/net/uring.h": 2, "src/persist/aof.cc": 2,
              "src/snapshot/snapshot.cc": 2}


def source(root, expected):
    root = Path(root)
    hits, scanned = [], 0
    for directory in ("src", "tests", "tools"):
        assert (root / directory).is_dir(), f"missing source directory: {directory}"
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue
            scanned += 1
            for line, text in enumerate(data.decode(errors="replace").splitlines(), 1):
                if PATTERN.search(text):
                    hits.append(dict(path=str(path.relative_to(root)), line=line, text=text))
    counts = Counter(hit["path"] for hit in hits)
    okay = counts == PRE_COUNTS if expected == "present" else not hits
    return dict(okay=okay, expected=expected, scanned_files=scanned, hits=hits,
                scope="all text files under src, tests, tools except Python bytecode",
                claim="removal inventory only; not a witness of SQE submission")


def controls(root, archive, binary, obj, db0_obj, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    checker = script.with_name("ttlstate_proof.py")
    jobs = [("source-positive", script,
             ["source", str(root), "--expect", "absent"], 0, None),
            ("identical-elf", checker, ["elf", str(binary), str(binary)], 0, None)]
    # Reintroduce both declaration and generated-call residue independently.
    with tarfile.open(archive) as pre:
        for name, relative, anchor in (
                ("restored-declaration", "src/net/uring.h", "    Ring() = default;\n"),
                ("restored-r7-call", "src/core/reorder.cc",
                 "        s->user_data = ur_tag(UrKind::TlsRecv, c);\n")):
            tree = output / name
            for directory in ("src", "tests", "tools"):
                shutil.copytree(root / directory, tree / directory,
                                ignore=shutil.ignore_patterns("__pycache__"))
            original = pre.extractfile(relative).read().decode()
            if name == "restored-declaration":
                line, = [line for line in original.splitlines()
                         if "void " + MARKER in line]
            else:
                line, = [line for line in original.splitlines() if PATTERN.search(line)]
            path = tree / relative
            text = path.read_text()
            assert text.count(anchor) == 1 and not PATTERN.search(text)
            path.write_text(text.replace(anchor, anchor + line + "\n"))
            jobs.append((name, script, ["source", str(tree), "--expect", "absent"],
                         1, "restored marker"))
    # All poisoned ELFs are copies with execution permission removed. Changing a
    # relocation or address must fail even if the executable bytes are untouched.
    specs = [("linked-text-byte", binary, "text"),
             ("normal-text-subsection-byte", obj, "subsection"),
             ("db0-text-subsection-byte", db0_obj, "subsection"),
             ("relocation-target", obj, "relocation"),
             ("linked-function-address", binary, "symbol"),
             ("linked-entry-point", binary, "entry"),
             ("allocated-data-byte", binary, "data")]
    for name, original, kind in specs:
        elf = Elf(original)
        data = bytearray(elf.data)
        if kind in ("text", "subsection", "data"):
            index = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                         if s[5] and ((s[2] & 4 and n == ".text") if kind == "text"
                         else (s[2] & 4 and n.startswith(".text.")) if kind == "subsection"
                         else (s[2] & 2 and n == ".rodata")))
            offset = elf.sections[index][4]
            data[offset] ^= 1
            label = "allocated" if kind == "data" else "executable"
            reason = f"{label} {elf.names[index]}: bytes differ"
        elif kind == "relocation":
            section = next(s for s in elf.sections if s[1] == 4 and s[5] and
                           s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            offset = section[4] + 16
            struct.pack_into("<q", data, offset, struct.unpack_from("<q", data, offset)[0] + 1)
            reason = "allocated relocation targets differ"
        elif kind == "symbol":
            table, index = next((table, index) for table, symbols in elf.tables.items()
                                for index, symbol in enumerate(symbols)
                                if symbol["info"] & 15 == 2 and symbol["size"] and
                                0 < symbol["sec"] < len(elf.sections) and
                                elf.sections[symbol["sec"]][2] & 4)
            offset = elf.sections[table][4] + index * elf.sections[table][9] + 8
            struct.pack_into("<Q", data, offset, struct.unpack_from("<Q", data, offset)[0] + 1)
            reason = "allocated symbol addresses/identities differ"
        else:
            offset = 24  # ELF64 e_entry
            struct.pack_into("<Q", data, offset, struct.unpack_from("<Q", data, offset)[0] + 1)
            reason = "ELF kind/machine/entry or program headers differ"
        poison = output / (name + ".NEVER-RUN")
        poison.write_bytes(data)
        poison.chmod(0o600)
        save(output / (name + "-mutation.json"),
             dict(source=str(original), copy=str(poison), offset=offset, kind=kind))
        jobs.append((name, checker, ["elf", str(original), str(poison)], 1, reason))
    results = []
    for name, driver, argv, expected, reason in jobs:
        report = output / (name + ".json")
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run([sys.executable, str(driver), *argv, "--output", str(report)],
                                    stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == expected, (name, result.returncode, expected)
        detail = json.loads(report.read_text())
        if reason == "restored marker":
            assert len(detail["hits"]) == 1 and PATTERN.search(detail["hits"][0]["text"])
        elif reason:
            assert reason in detail["errors"], (name, detail)
        results.append(dict(control=name, returncode=result.returncode, expected=expected,
                            exact_rejection=reason, report=str(report)))
    for name, reason in (("linked-function-address", "allocated symbol addresses/identities differ"),
                         ("linked-entry-point", "ELF kind/machine/entry or program headers differ"),
                         ("allocated-data-byte", "allocated .rodata: bytes differ")):
        destination = output / ("rejected-PAD-" + name)
        log_path = output / ("pad-guard-" + name + ".log")
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, str(script), "pad", str(binary),
                                     str(output / (name + ".NEVER-RUN")), str(destination),
                                     "--output", str(destination) + ".json"],
                                    stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == 1 and reason in log_path.read_text(), name
        assert not destination.exists(), "invalid layout/data must not create a PAD arm"
        results.append(dict(control="pad-guard-" + name, returncode=result.returncode,
                            expected=1, exact_rejection=reason, arm_created=False))
    return dict(okay=True, results=results, executed_elf_arms=False)


def pad(pre, post, output):
    """A PRE copy is a kind-A twin only after proving POST has the same layout."""
    pre, post, output = Path(pre).resolve(), Path(post).resolve(), Path(output).resolve()
    comparison = compare_files(pre, post)
    executable = {row["section"] for row in comparison["executable"]}
    permitted = {f"{label} {name}: bytes differ"
                 for label in ("executable", "allocated") for name in executable}
    assert set(comparison["errors"]) <= permitted, comparison["errors"]
    # Check the exact function name/address/size table as well as the checker's
    # allocated-symbol audit (which permits spelling-only local asm-label changes).
    def functions(path):
        return sorted((s["name"], s["info"], s["value"], s["size"])
                      for s in Elf(path).symbols if s["info"] & 15 == 2)
    assert functions(pre) == functions(post), "PRE/POST function tables differ"
    # Reuse the existing raw dump writer without changing the production binary.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pad-capture-", dir=output.parent) as tmp:
        work = Path(tmp)
        (work / "build").mkdir()
        shutil.copy2(pre, work / "build/tomokv")
        (work / "objects.json").write_text("[]\n")
        cwd = Path.cwd()
        try:
            os.chdir(work)
            capture("objects.json", output, [])
        finally:
            os.chdir(cwd)
    identity = compare_files(pre, output / "artifacts/tomokv")
    assert identity["okay"] and identity["whole_file_equal"], "PAD must be an exact PRE copy"
    return dict(okay=True, kind="A: PRE behavior with POST text size/layout",
                method="separate, unmodified PRE copy; all POST function addresses/layout match",
                pre_pad=identity, pre_post=comparison, function_count=len(functions(pre)),
                post_function_table_equal=True, mainline_controlled_null="PENDING MAINLINE")


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), "pin to CPUs 112-127"
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("source")
    p.add_argument("root")
    p.add_argument("--expect", choices=("present", "absent"), required=True)
    p = sub.add_parser("controls")
    for arg in ("root", "pre_archive", "binary", "object", "db0_object", "destination"):
        p.add_argument(arg)
    p = sub.add_parser("pad")
    for arg in ("pre", "post", "destination"):
        p.add_argument(arg)
    for p in sub.choices.values():
        p.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "source":
        result = source(args.root, args.expect)
    elif args.command == "controls":
        result = controls(args.root, args.pre_archive, args.binary, args.object,
                          args.db0_object, args.destination)
    else:
        result = pad(args.pre, args.post, args.destination)
    save(args.output, result)
    print(("PASS" if result["okay"] else "FAIL"), args.command, args.output)
    return 0 if result["okay"] else 1


if __name__ == "__main__":
    sys.exit(main())
