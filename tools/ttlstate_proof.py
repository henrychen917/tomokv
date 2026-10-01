#!/usr/bin/env python3
"""Offline removal inventory and raw ELF identity proof; never execute an ELF arm.

Run under taskset -c 112-127. Capture both builds at the same source/output paths.
Debug information and the debug-dependent build ID are reported separately from
executable bytes, allocated data, relocation targets, and linked addresses.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from lbstall_artifacts import Elf


REMOVED = ("Ttl" + "State", "ttl_" + "state")
PATTERN = re.compile(r"\b(?:" + "|".join(REMOVED) + r")\b")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def source(root, expected):
    root = Path(root)
    hits = []
    scanned = 0
    for directory in ("src", "tests", "tools"):
        assert (root / directory).is_dir(), f"missing source directory: {directory}"
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            raw = path.read_bytes()
            if b"\0" in raw:
                continue
            scanned += 1
            for line, text in enumerate(raw.decode(errors="replace").splitlines(), 1):
                if PATTERN.search(text):
                    hits.append(dict(path=str(path.relative_to(root)), line=line, text=text))
    if expected == "present":
        # Only the definition, its two self-return types, and the unused accessor.
        locations = [(h["path"], h["line"]) for h in hits]
        want = [("src/store/kvobj.h", 228)] + [
            ("src/store/store_ttl.h", line) for line in (23, 37, 45)]
        okay = locations == want
    else:
        okay = not hits
    return dict(okay=okay, expected=expected, scanned_files=scanned, hits=hits,
                scope="all text files under src, tests, tools (excluding Python bytecode)",
                claim="source inventory only; no runtime coverage of the unused accessor")


def section_name(elf, index):
    return elf.names[index] if 0 < index < len(elf.sections) else f"SHN:{index}"


def symbol_signature(elf, table, index):
    symbol = elf.tables[table][index]
    section = elf.sections[table]
    other = elf.data[section[4] + index * section[9] + 5]
    return (symbol["name"], symbol["info"], other,
            section_name(elf, symbol["sec"]), symbol["value"], symbol["size"])


def relocations(elf):
    rows = []
    for section, name in zip(elf.sections, elf.names):
        if section[1] not in (4, 9):  # RELA / REL
            continue
        target = section[7]
        if not (section[2] & 2 or
                (target < len(elf.sections) and elf.sections[target][2] & 2)):
            continue  # DWARF relocations are not production relocations.
        assert section[1] == 4, f"unsupported allocated REL section: {name}"
        for at in range(section[4], section[4] + section[5], section[9]):
            offset, info, addend = struct.unpack_from("<QQq", elf.data, at)
            rows.append((name, section_name(elf, target), offset, info & 0xffffffff,
                         symbol_signature(elf, section[6], info >> 32), addend))
    return sorted(rows)


def addresses(elf):
    rows = []
    for table, symbols in elf.tables.items():
        for index, symbol in enumerate(symbols):
            section = symbol["sec"]
            if 0 < section < len(elf.sections) and elf.sections[section][2] & 2:
                rows.append((elf.names[table], symbol_signature(elf, table, index)))
    return sorted(rows)


def compare_addresses(before, after):
    old, new = Counter(addresses(before)), Counter(addresses(after))
    removed, added = list((old - new).elements()), list((new - old).elements())
    groups = []
    for rows in (removed, added):
        by_address = defaultdict(list)
        for table, (name, info, other, section, value, size) in rows:
            # Existing KvObj/RL topology asm uses %= for local patch-marker names. GCC may
            # renumber these even when every emitted byte/address is unchanged.
            # Permit ONLY spelling changes, retaining every address and attribute.
            if not (table == ".symtab" and info == 0 and other == 0 and size == 0 and
                    re.fullmatch(r"tomo_(?:multidb2_pad|rltopo_demote)_[0-9]+", name)):
                return False, []
            by_address[(table, info, other, section, value, size)].append(name)
        groups.append(by_address)
    a, b = groups
    if a.keys() != b.keys() or any(len(a[key]) != len(b[key]) for key in a):
        return False, []
    renamed = [dict(attributes=key, pre=old_name, post=new_name)
               for key in sorted(a)
               for old_name, new_name in zip(sorted(a[key]), sorted(b[key]))]
    return True, renamed


def selected_sections(elf, flag):
    rows = {}
    for index, (section, name) in enumerate(zip(elf.sections, elf.names)):
        if not section[2] & flag:
            continue
        assert name not in rows, f"duplicate section name: {name}"
        raw = b"" if section[1] == 8 else elf.section_data(index)  # NOBITS
        # File offsets matter for final load mappings, not relocatable containers.
        metadata = [section[j] for j in (1, 2, 3, 5, 8, 9)]
        if elf.kind != 1:
            metadata.append(section[4])
        rows[name] = (metadata, raw)
    return rows


def program_headers(elf):
    offset = struct.unpack_from("<Q", elf.data, 32)[0]
    size, count = struct.unpack_from("<HH", elf.data, 54)
    return elf.data[offset:offset + size * count]


def compare_files(before, after):
    a, b = Elf(before), Elf(after)
    errors = []
    executable = []
    for flag, label in ((4, "executable"), (2, "allocated")):
        old, new = selected_sections(a, flag), selected_sections(b, flag)
        if old.keys() != new.keys():
            errors.append(f"{label} section inventory differs")
        for name in sorted(old.keys() | new.keys()):
            if name not in old or name not in new:
                continue
            # Build IDs include DWARF; never exempt an executable section.
            if label == "allocated" and name == ".note.gnu.build-id":
                continue
            layout_equal = old[name][0] == new[name][0]
            raw_equal = old[name][1] == new[name][1]  # no masking/normalization
            if not layout_equal:
                errors.append(f"{label} {name}: layout differs")
            if not raw_equal:
                errors.append(f"{label} {name}: bytes differ")
            if flag == 4:
                executable.append(dict(section=name, bytes=len(old[name][1]),
                    pre_sha256=digest(old[name][1]), post_sha256=digest(new[name][1]),
                    layout_equal=layout_equal, raw_equal=raw_equal))
    if not executable:
        errors.append("no executable sections found")
    if relocations(a) != relocations(b):
        errors.append("allocated relocation targets differ")
    address_equal, renamed_labels = compare_addresses(a, b)
    if not address_equal:
        errors.append("allocated symbol addresses/identities differ")
    if a.data[16:32] != b.data[16:32] or program_headers(a) != program_headers(b):
        errors.append("ELF kind/machine/entry or program headers differ")
    different_sections = []
    old = {name: i for i, name in enumerate(a.names)}
    new = {name: i for i, name in enumerate(b.names)}
    for name in sorted(old.keys() | new.keys()):
        if name not in old or name not in new:
            different_sections.append(name)
        elif a.sections[old[name]][1] != 8 and \
                a.section_data(old[name]) != b.section_data(new[name]):
            different_sections.append(name)
    return dict(okay=not errors, before=str(before), after=str(after), errors=errors,
                pre_sha256=digest(a.data), post_sha256=digest(b.data),
                whole_file_equal=a.data == b.data, executable=executable,
                address_equal=address_equal, renamed_local_labels=renamed_labels,
                relocation_count=len(relocations(a)), symbol_count=len(addresses(a)),
                different_sections=different_sections)


def capture(inventory, output, extras):
    output = Path(output)
    assert not output.exists(), f"refusing to overwrite an arm: {output}"
    paths = [row["object"] for row in json.loads(Path(inventory).read_text())]
    paths += ["build/tomokv"] + extras
    assert len(paths) == len(set(paths)), "duplicate artifact"
    manifest = {}
    for name in paths:
        path = Path(name)
        relative = path.relative_to("build")
        dest = output / "artifacts" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        elf = Elf(dest)
        dumps = output / "dumps" / relative
        dumps.mkdir(parents=True)
        for filename, argv in (
                ("readelf.txt", ["readelf", "-W", "-h", "-l", "-S", "-s", "-r"]),
                ("objdump.txt", ["objdump", "-drw"]),
                ("nm.txt", ["nm", "-anSC"])):
            with (dumps / filename).open("wb") as out:
                subprocess.run(argv + [str(dest)], stdout=out, check=True)
        sections = []
        for index, (section, section_name_) in enumerate(zip(elf.sections, elf.names)):
            if section[2] & 4:
                filename = f"{index:05d}-{digest(section_name_.encode())[:12]}.bin"
                raw = elf.section_data(index)
                (dumps / filename).write_bytes(raw)
                sections.append(dict(name=section_name_, file=filename, bytes=len(raw),
                                     address=section[3], align=section[8], sha256=digest(raw)))
        save(dumps / "sections.json", sections)
        save(dumps / "relocations.json", relocations(elf))
        save(dumps / "addresses.json", addresses(elf))
        manifest[str(relative)] = dict(sha256=digest(elf.data), bytes=len(elf.data),
                                      executable_sections=len(sections))
    save(output / "manifest.json", manifest)
    return dict(okay=True, artifacts=len(manifest), output=str(output))


def compare_arms(before, after):
    before, after = Path(before), Path(after)
    a = json.loads((before / "manifest.json").read_text())
    b = json.loads((after / "manifest.json").read_text())
    assert a.keys() == b.keys(), "arm artifact inventory differs"
    rows = []
    for name in sorted(a):
        pre, post = before / "artifacts" / name, after / "artifacts" / name
        assert digest(pre.read_bytes()) == a[name]["sha256"], f"PRE changed: {name}"
        assert digest(post.read_bytes()) == b[name]["sha256"], f"POST changed: {name}"
        result = compare_files(pre, post)
        rows.append(dict(artifact=name, **result))
    assert rows, "empty arm inventory"
    return dict(okay=all(row["okay"] for row in rows), rows=rows)


def controls(root, pre_header, binary, obj, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    tree = output / "restored-accessor"
    for directory in ("src", "tests", "tools"):
        shutil.copytree(root / directory, tree / directory,
                        ignore=shutil.ignore_patterns("__pycache__"))
    header = tree / "src/store/kvobj.h"
    old_line, = [line for line in Path(pre_header).read_text().splitlines()
                 if REMOVED[1] in line]
    text = header.read_text()
    anchor = "    bool has_ttl() const { return expire_at_ms() >= 0; }\n"
    assert text.count(anchor) == 1 and not PATTERN.search(text)
    header.write_text(text.replace(anchor, anchor + old_line + "\n"))
    jobs = [("source-positive", ["source", str(root), "--expect", "absent"], 0, None),
            ("restored-accessor", ["source", str(tree), "--expect", "absent"], 1, None),
            ("identical-elf", ["elf", str(binary), str(binary)], 0, None)]
    for name, source_path, kind in (("executable-byte", binary, "text"),
                                   ("text-subsection-byte", obj, "subsection"),
                                   ("relocation-target", obj, "relocation"),
                                   ("linked-address", binary, "symbol"),
                                   ("local-label-address", binary, "label")):
        elf = Elf(source_path)
        data = bytearray(elf.data)
        if kind in ("text", "subsection"):
            index = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                         if s[2] & 4 and s[5] and
                         (n == ".text" if kind == "text" else n.startswith(".text.")))
            data[elf.sections[index][4]] ^= 1
            reason = f"executable {elf.names[index]}: bytes differ"
        elif kind == "relocation":
            section = next(s for s in elf.sections if s[1] == 4 and s[5] and
                           s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            offset = section[4] + 16  # first RELA addend
            struct.pack_into("<q", data, offset, struct.unpack_from("<q", data, offset)[0] + 1)
            reason = "allocated relocation targets differ"
        else:
            table, index = next((table, index) for table, symbols in elf.tables.items()
                               for index, symbol in enumerate(symbols)
                               if (symbol["name"].startswith("tomo_multidb2_pad_")
                                   if kind == "label" else
                                   symbol["info"] & 15 == 2 and symbol["size"]) and
                               0 < symbol["sec"] < len(elf.sections) and
                               elf.sections[symbol["sec"]][2] & 4)
            offset = elf.sections[table][4] + index * elf.sections[table][9] + 8
            struct.pack_into("<Q", data, offset, struct.unpack_from("<Q", data, offset)[0] + 1)
            reason = "allocated symbol addresses/identities differ"
        corrupt = output / (name + ".NEVER-RUN")
        corrupt.write_bytes(data)
        corrupt.chmod(0o600)
        jobs.append((name, ["elf", str(source_path), str(corrupt)], 1, reason))
    results = []
    for name, argv, expected, reason in jobs:
        report = output / (name + ".json")
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run([sys.executable, str(script), *argv, "--output", str(report)],
                                    stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == expected, (name, result.returncode, expected)
        detail = json.loads(report.read_text())
        if reason:
            assert reason in detail["errors"], (name, detail)
        if name == "restored-accessor":
            assert len(detail["hits"]) == 1 and REMOVED[1] in detail["hits"][0]["text"]
        results.append(dict(control=name, returncode=result.returncode,
                            expected=expected, rejection=reason))
    return dict(okay=True, results=results)


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), "pin to CPUs 112-127"
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("source")
    p.add_argument("root")
    p.add_argument("--expect", choices=("present", "absent"), required=True)
    p = sub.add_parser("capture")
    p.add_argument("inventory")
    p.add_argument("destination")
    p.add_argument("--extra", action="append", default=[])
    for command in ("elf", "compare"):
        p = sub.add_parser(command)
        p.add_argument("before")
        p.add_argument("after")
    p = sub.add_parser("controls")
    for arg in ("root", "pre_header", "binary", "object", "destination"):
        p.add_argument(arg)
    for p in sub.choices.values():
        p.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "source":
        result = source(args.root, args.expect)
    elif args.command == "capture":
        result = capture(args.inventory, args.destination, args.extra)
    elif args.command == "elf":
        result = compare_files(args.before, args.after)
    elif args.command == "compare":
        result = compare_arms(args.before, args.after)
    else:
        result = controls(args.root, args.pre_header, args.binary, args.object, args.destination)
    save(args.output, result)
    print(("PASS" if result["okay"] else "FAIL"), args.command, args.output)
    return 0 if result["okay"] else 1


if __name__ == "__main__":
    sys.exit(main())
