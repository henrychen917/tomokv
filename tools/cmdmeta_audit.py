#!/usr/bin/env python3
"""EX9 offline ordinary-command byte, instruction and linked-layout receipts; no ELF execution."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import instructions


def body(elf, symbol):
    section = elf.sections[symbol["sec"]]
    offset = section[4] + symbol["value"] - (0 if elf.kind == 1 else section[3])
    return memoryview(elf.data)[offset:offset + symbol["size"]]


def functions(elf):
    groups = defaultdict(list)
    for symbol in elf.symbols:
        if symbol["info"] & 15 == 2 and 0 < symbol["sec"] < len(elf.sections):
            if elf.sections[symbol["sec"]][2] & 4:
                groups[symbol["name"]].append(symbol)
    return {(name, index): symbol for name, symbols in groups.items()
            for index, symbol in enumerate(sorted(symbols, key=lambda s: (s["value"], s["size"])))}


def save(path, value):
    data = (json.dumps(value, indent=2) + "\n").encode()
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == ".gz" else data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pre", type=Path)
    parser.add_argument("post", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pad", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # The comprehensive existing relocation-aware audit is an independent prerequisite.
    audit = json.loads((args.output / "body-audit/summary.json").read_text())
    changed = json.loads((args.output / "body-audit/changed-bodies.json").read_text())
    assert set(audit["changed_objects"]) <= {"src/cmd/cmdmeta.o", "db0/src/cmd/cmdmeta.o"}, audit
    ordinary, object_sections = [], []
    object_relocations = defaultdict(list)
    for before in sorted(args.pre.rglob("*.o")):
        relative = before.relative_to(args.pre)
        after = args.post / relative
        left, right = Elf(before), Elf(after)
        la, lb = functions(left), functions(right)
        assert la.keys() == lb.keys(), relative
        code_a = {n: left.section_data(i) for i, n in enumerate(left.names) if left.sections[i][2] & 4}
        code_b = {n: right.section_data(i) for i, n in enumerate(right.names) if right.sections[i][2] & 4}
        equal = code_a == code_b
        object_sections.append(dict(object=str(relative), executable_sections_equal=equal,
                                    executable_bytes=sum(map(len, code_a.values()))))
        if before.name != "cmdmeta.o":
            assert equal, (relative, "ordinary object code changed")
        for key in sorted(la):
            name, occurrence = key
            old, new = la[key], lb[key]
            if body(left, old) == body(right, new):
                relocated = set()
                targets = []
                for offset, kind, target, addend in left.relocs.get(old["sec"], []):
                    at = offset - old["value"]
                    if not 0 <= at < old["size"]:
                        continue
                    width = {1: 8, 2: 4, 4: 4, 9: 4, 10: 4, 11: 4, 23: 4, 24: 8,
                             41: 4, 42: 4}.get(kind)
                    assert width, (relative, name, kind)
                    relocated.update(range(at, at + width))
                    targets.append(dict(offset=at, width=width, type=kind,
                                        target=left.target(target, addend, kind)))
                object_relocations[(name, old["size"])].append((str(relative), relocated, targets))
            if not re.search(r"(?:\d+cmd_)", name):
                continue
            a, b = body(left, la[key]), body(right, lb[key])
            assert a == b, (relative, name)
            ordinary.append(dict(object=str(relative), symbol=name, occurrence=occurrence,
                                 bytes=len(a), sha256=hashlib.sha256(a).hexdigest(), raw_equal=True))
    assert ordinary and any(row["object"].startswith("db0/") for row in ordinary)
    save(args.output / "ordinary-command-bodies.json", ordinary)
    save(args.output / "executable-objects.json", object_sections)

    # Every changed function gets static instruction counts and its concrete table-dependent reason.
    for row in changed:
        for arm, root in (("pre", args.pre), ("post", args.post)):
            dump = subprocess.check_output(["objdump", "-dw", "--disassemble=" + row["symbol"],
                                            str(root / row["object"])], text=True)
            (args.output / (arm + "-" + row["symbol"] + ".asm")).write_text(dump)
            row[arm + "_instructions"] = len(instructions(dump))
        name = row["name"]
        if "child_count(" in name or "reply_info_row(" in name:
            reason = "embedded metadata scan end moves from 374 to 341 rows; index data shrinks"
        elif "command_metadata_lookup(" in name:
            reason = "table bounds 374 -> 341 and maximum qualified name 29 -> 23"
        elif "command_metadata_resolve(" in name:
            reason = "maximum qualified name 29 -> 23 (stack scratch/bounds derived from table)"
        elif "command_metadata_size(" in name or "command_metadata_at(" in name:
            reason = "metadata row count 374 -> 341"
        elif "command_metadata_collect_keys(" in name or "command_metadata_key_flag_name(" in name:
            reason = "literal code unchanged; relocation addends follow moved key-flag data"
        else:
            raise AssertionError((name, "unexplained changed metadata function"))
        row["reason"] = reason
    save(args.output / "changed-metadata-bodies.json", changed)

    pre, post = Elf(args.pre / "tomokv"), Elf(args.post / "tomokv")
    a, b = functions(pre), functions(post)
    assert a.keys() == b.keys(), "linked symbol inventory moved"
    layout_changes, byte_changes = [], []
    metadata_symbols = {row["symbol"] for row in changed}
    for key in sorted(a):
        x, y = a[key], b[key]
        name, occurrence = key
        if (x["value"], x["size"]) != (y["value"], y["size"]):
            layout_changes.append(dict(symbol=name, occurrence=occurrence,
                                       pre=[x["value"], x["size"]], post=[y["value"], y["size"]]))
        aa, bb = body(pre, x), body(post, y)
        if aa != bb:
            offsets = {i for i, (l, r) in enumerate(zip(aa, bb)) if l != r}
            matches = [(obj, targets) for obj, relocated, targets in object_relocations[(name, len(aa))]
                       if offsets <= relocated]
            if name in metadata_symbols:
                reason = "metadata helper: bounds/name limit or metadata-data relocation (changed-metadata-bodies.json)"
            elif matches:
                reason = "all differing bytes lie in ELF relocation fields of a byte-identical object body"
            else:
                reason = "linker/startup body outside the command-handler inventory"
            if re.search(r"(?:\d+cmd_)", name):
                assert matches, (name, "ordinary linked command has non-relocation byte differences")
            byte_changes.append(dict(symbol=name, occurrence=occurrence,
                                     pre_sha256=hashlib.sha256(aa).hexdigest(),
                                     post_sha256=hashlib.sha256(bb).hexdigest(),
                                     changed_offsets=sorted(offsets),
                                     relocation_object=matches[0][0] if matches else None,
                                     relocation_targets=matches[0][1] if matches else [], reason=reason))
    save(args.output / "linked-layout-changes.json", layout_changes)
    save(args.output / "linked-byte-changes.json.gz", byte_changes)
    assert not layout_changes, "PRE cannot serve as the exact POST text-layout behavior twin"
    # No text padding is needed: PRE already has candidate function addresses/sizes. Keep an
    # explicitly degenerate A twin. It does NOT control for the smaller metadata/data sections.
    args.pad.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.pre / "tomokv", args.pad)
    assert args.pad.read_bytes() == pre.data
    summary = dict(ordinary_command_bodies=len(ordinary), ordinary_raw_equal=len(ordinary),
                   executable_objects=len(object_sections),
                   identical_executable_objects=sum(row["executable_sections_equal"] for row in object_sections),
                   changed_metadata_bodies=len(changed), linked_functions=len(a),
                   linked_layout_changes=len(layout_changes), linked_raw_byte_changes=len(byte_changes),
                   linked_changes_confined_to_relocations=sum(bool(row["relocation_object"]) for row in byte_changes),
                   linked_ordinary_relocation_changes=sum(bool(re.search(r"(?:\d+cmd_)", row["symbol"])) for row in byte_changes),
                   text_bytes={"PRE": pre.sections[pre.names.index(".text")][5],
                               "POST": post.sections[post.names.index(".text")][5]},
                   pad=dict(kind="A: PRE behavior with POST text size and every function address/size",
                            sha256=hashlib.sha256(pre.data).hexdigest(), identical_to="PRE",
                            limitation="Degenerate text-layout control; metadata/data sizes differ from POST. No performance claim."))
    save(args.output / "cmdmeta-audit.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
