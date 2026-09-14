#!/usr/bin/env python3
"""Build the R2 PRE-behaviour placement control without running an executable.

Adapted from the shared R7 tools/reorder_pad.py (1bc8e6f271).
The measured POST is an immutable input. Reuse PRE release objects, split only
the two changed translation units' existing assembly into linkable functions,
and let ld fill unused POST slots with unreachable NOPs. A full linked-body audit
is required: a successful link alone is not evidence of a behaviour twin.

This control records three placement exceptions; it is not a literal match of
every POST symbol address. No exception is permitted in PRE body equivalence.
"""

import argparse
import bisect
import collections
import hashlib
import json
import os
import re
import shlex
import struct
import subprocess
import sys
from pathlib import Path

PRE_SHA = "4e19f4049a24769516fe89ea13d3d054e2ab2898e9fe769faa78277f849fef32"
POST_SHA = "fd8be3d0a8b02a1674db34ddb9f1bd33236908e1b13205bebe3dab479b5ec48c"
BASE = Path("build/reorder-R2-arms/pre")
PRE = Path("build/tomokv-R2-pre")
POST = Path("build/tomokv-R2-post")
OUT = Path("build/r2-pad-A")
PAD = Path("build/tomokv-R2-pad-A")
CANDIDATE = OUT / "candidate"
COPY = OUT / "post-layout-reference"
SPLIT = {"src/main.o": "main", "src/core/rl2s.o": "rl2s"}
PLAIN = {".text", ".text.unlikely", ".text.startup"}
CALLBACK = ("_ZZN4tomo8WbEngine10serve_implILb0ELb1ELb1ELb{}ELb0ELb0EEE"
            "bRNS_6ClientEPbENKUlRNS_2OpEE_clES6_")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(*argv):
    return subprocess.check_output(argv, text=True)


class Elf:
    """Read the ELF64 section/symbol metadata used to construct the linker map."""

    def __init__(self, path):
        self.path = Path(path)
        data = self.path.read_bytes()
        require(data[:6] == b"\x7fELF\x02\x01", "expected little-endian ELF64")
        header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
        require(header[2] == 62, "expected x86-64 ELF")
        raw = [struct.unpack_from("<IIQQQQIIQQ", data, header[6] + i * header[11])
               for i in range(header[12])]
        names = raw[header[13]]
        names = data[names[4]:names[4] + names[5]]
        self.sections = {}
        self.by_index = []
        self.symbols = []
        for i, sec in enumerate(raw):
            name = names[sec[0]:].split(b"\0", 1)[0].decode()
            entry = dict(name=name, index=i, address=sec[3], size=sec[5],
                         align=sec[8], flags=sec[2], offset=sec[4])
            self.sections[name] = entry
            self.by_index.append(entry)
            if sec[1] != 2:
                continue
            strings = raw[sec[6]]
            strings = data[strings[4]:strings[4] + strings[5]]
            for at in range(sec[4], sec[4] + sec[5], sec[9]):
                n, info, other, section, addr, size = struct.unpack_from("<IBBHQQ", data, at)
                self.symbols.append(dict(name=strings[n:].split(b"\0", 1)[0].decode(),
                                         type=info & 15, section=section, address=addr,
                                         size=size))

    def functions(self, section=None):
        return [s for s in self.symbols if s["type"] == 2 and s["size"] and
                (section is None or s["section"] == self.sections[section]["index"])]


def inputs(path):
    lines = Path(path).read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(".text "))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(".fini "))
    result = []
    pending = None
    for line in lines[start + 1:end]:
        match = re.fullmatch(r" (\.[^ ]+)(?:\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(.+))?", line)
        if match:
            if match[2]:
                result.append(dict(section=match[1], address=int(match[2], 16),
                                   size=int(match[3], 16), object=match[4]))
                pending = None
            else:
                pending = match[1]
        elif pending:
            match = re.fullmatch(r"\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(.+)", line)
            if match:
                result.append(dict(section=pending, address=int(match[1], 16),
                                   size=int(match[2], 16), object=match[3]))
                pending = None
    require(result, "empty linker map")
    return [r for r in result if r["size"]]


def original_object(post_object):
    if post_object.startswith("build/src/"):
        return str(BASE / post_object)
    return post_object


def function_sections(obj, tag):
    result = {}
    for section in sorted(PLAIN):
        for sym in obj.functions(section):
            # Aliases at one address share one section and one physical body.
            name = f".text.r2pad.{tag}.{sym['section']}.{sym['address']:x}"
            result[sym["name"]] = (name, sym["size"])
    return result


def freeze_branches(lines, tag):
    # GAS relaxation can choose a shorter backward branch after section splitting,
    # even though the source instruction is unchanged. Emit PRE's opcode/width
    # with an ordinary symbolic displacement, so every internal NOP stays put.
    path = next((BASE / "build") / p for p, t in SPLIT.items() if t == tag)
    original = Elf(path)
    sections = collections.defaultdict(dict)
    section = None
    for line in run("objdump", "-dw", str(path)).splitlines():
        match = re.fullmatch(r"Disassembly of section (.+):", line)
        if match:
            section = match[1]
        match = re.match(r"\s*([0-9a-f]+):\s*((?:[0-9a-f]{2} )+)\s*(.*)", line)
        if match and re.match(r"j[a-z]+\s+[^*\s]", match[3]):
            sections[section][int(match[1], 16)] = bytes.fromhex(match[2])
    branches = {}
    for sym in original.functions():
        rows = sections[original.by_index[sym["section"]]["name"]]
        branches[sym["name"]] = [raw for at, raw in rows.items()
                                 if sym["address"] <= at < sym["address"] + sym["size"]]
    result = []
    active = None
    index = 0
    seen = {}
    for line in lines:
        if line.endswith(":\n") and line.rstrip()[:-1] in branches:
            if active:
                require(index == len(branches[active]), f"branch count mismatch: {active}")
                seen[active] = index
            active = line.rstrip()[:-1]
            index = 0
        match = re.fullmatch(r"\s*(j[a-z]+)\s+([^*\s]+)\s*", line)
        if match and active:
            require(index < len(branches[active]), f"extra assembly branch: {active}")
            raw = branches[active][index]
            index += 1
            if match[2].endswith("@PLT"):
                require(len(raw) == 5 and raw[0] == 0xe9, "unexpected PLT branch encoding")
                result.append(line)  # External PLT jumps always retain rel32.
                continue
            width = 4 if len(raw) >= 5 else 1
            opcode = ",".join(hex(b) for b in raw[:-width])
            directive = ".long" if width == 4 else ".byte"
            line = f"\t.byte {opcode}\n\t{directive} {match[2]} - . - {width}\n"
        result.append(line)
    if active:
        require(index == len(branches[active]), f"final branch count mismatch: {active}")
        seen[active] = index
    (OUT / f"branches-{tag}.json").write_text(json.dumps(seen, indent=2) + "\n")
    return result


def split_assembly(tag, funcs):
    """Change section directives and ELF sizes only; preserve all instructions.

    GCC returns to .text before emitting a hot function's .size after its cold
    fragment. Use PRE's size metadata because each fragment now has its own input
    section. The independent audit checks real decoded bytes and widths too.
    """
    source = OUT / f"{tag}.s"
    target = OUT / f"{tag}.split.s"
    # DWARF's translation-unit-wide range subtraction assumes one .text input.
    # Drop only nonloaded debug directives in these two reassembled objects;
    # retain CFI, LSDA, properties, symbols and every instruction/data directive.
    lines = []
    debug = False
    with source.open() as src:
        for line in src:
            directive = re.match(r'\s*\.section\s+([^,\s]+)', line)
            if directive:
                debug = directive[1].startswith(".debug_")
            symbol_directive = re.match(r"\s*\.(?:hidden|weak|globl|type|size|ident)\s", line)
            if (not debug or symbol_directive) and not line.lstrip().startswith((".loc ", ".loc\t", ".file ", ".file\t")):
                lines.append(line)
    lines = freeze_branches(lines, tag)
    positions = {line.rstrip()[:-1]: i for i, line in enumerate(lines) if line.endswith(":\n")}
    switches = {}
    for symbol, (section, _) in funcs.items():
        if symbol not in positions:  # Constructor/destructor .set aliases.
            continue
        at = positions[symbol]
        anchor = at
        # Cold fragments put CFI before their .type/label. Move that prologue
        # with the body instead of starting an unwind record in the prior slot.
        for j in range(at - 1, -1, -1):
            value = lines[j].strip()
            if value.startswith((".size", ".cfi_endproc")) or value.endswith(":"):
                break
            if not value.startswith("."):
                break
            anchor = j
            if value == ".text" or value.startswith(".section"):
                break
        switches[anchor] = section
        # GCC emits the cold LSDA base before the HOT body, long before the
        # cold body itself. Keep both zero-sized anchors with their fragment.
        for j in range(at - 1, max(-1, at - 20), -1):
            label = lines[j].strip()
            if label.startswith(".LHOTB") and label.endswith(":"):
                switches[j] = section
            if label.startswith(".LCOLDB") and label.endswith(":"):
                cold = funcs.get(symbol + ".cold")
                require(cold is not None, f"missing cold fragment for {symbol}")
                switches[j] = cold[0]
                break
            if label and not label.startswith("."):
                break
    current = {}
    original_section = ".text"
    with target.open("w") as dst:
        for i, line in enumerate(lines):
            directive = re.match(r'\s*\.section\s+([^,\s]+)', line)
            if line.strip() == ".text" or directive:
                original_section = directive[1] if directive else ".text"
            if i in switches:
                require(original_section in PLAIN, f"unexpected original section at line {i}: {original_section}")
                current[original_section] = switches[i]
                dst.write(f'\t.section {switches[i]},"ax",@progbits\n')
            if (line.strip() == ".text" or directive) and original_section in current:
                line = f'\t.section {current[original_section]},"ax",@progbits\n'
            if line.lstrip().startswith(".size"):
                match = re.fullmatch(r"\s*\.size\s+([^,]+),\s*\.\s*-\s*\1\s*", line)
                if match and match[1] in funcs:
                    line = f"\t.size {match[1]}, {funcs[match[1]][1]}\n"
            dst.write(line)
    require(switches, f"no functions split in {source}")
    return target


def prepare():
    require(sha(PRE) == PRE_SHA and sha(POST) == POST_SHA, "reference binary SHA changed")
    OUT.mkdir(exist_ok=True, parents=True)
    if COPY.exists():
        require(COPY.read_bytes() == POST.read_bytes(), "POST-v2 copy has different bytes")
    else:
        COPY.write_bytes(POST.read_bytes())
        COPY.chmod(POST.stat().st_mode)

    old_recipe = json.loads(Path("build/r2-noop/pad-recipe.json").read_text())
    pre_argv = [a for a in old_recipe["link_argv"] if not a.endswith("/padding.o")]
    pre_argv[pre_argv.index("-o") + 1] = str(OUT / "pre-layout")
    # Relative object names let the script work in this worktree after relocation.
    root = str(Path.cwd()) + "/"
    pre_argv = [a.removeprefix(root) for a in pre_argv]
    post_argv = json.loads(Path("build/r2-noop/post-link.json").read_text())
    post_argv[post_argv.index("-o") + 1] = str(OUT / "post-layout")
    recipes = []
    for name, argv in [("pre", pre_argv), ("post", post_argv)]:
        recipes.append(shlex.join(argv + [f"-Wl,-Map={OUT}/{name}.map"]))
    (OUT / "maps.mk").write_text("all:\n" + "".join("\t" + r + "\n" for r in recipes))
    (OUT / "pre-link.json").write_text(json.dumps(pre_argv, indent=2) + "\n")
    subprocess.run(["make", "-j8", "-f", str(OUT / "maps.mk")], check=True)
    require((OUT / "pre-layout").read_bytes() == PRE.read_bytes(), "PRE relink is not reproducible")
    require((OUT / "post-layout").read_bytes() == POST.read_bytes(), "POST relink is not reproducible")
    assembly = ["all: " + " ".join(str(OUT / f"{tag}.s") for tag in SPLIT.values()) + "\n"]
    for obj, tag in SPLIT.items():
        source = obj.removesuffix(".o") + ".cc"
        assembly.append(f"{OUT}/{tag}.s: {BASE}/{source}\n"
                        f"\tcd {BASE} && g++ -std=c++20 -O2 -g -Wall -Wextra -march=native "
                        f"-pthread -DTOMO_JEMALLOC -I. -S {source} -o {OUT.resolve()}/{tag}.s\n")
    (OUT / "assembly.mk").write_text("".join(assembly))
    subprocess.run(["make", "-j8", "-f", str(OUT / "assembly.mk")], check=True)


def layout():
    pre = Elf(PRE)
    post = Elf(POST)
    pre_inputs = inputs(OUT / "pre.map")
    post_inputs = inputs(OUT / "post.map")
    post_sections = {(original_object(r["object"]), r["section"]): r for r in post_inputs}
    objects = {r["object"]: Elf(r["object"]) for r in pre_inputs}
    post_objects = {r["object"]: Elf(r["object"]) for r in post_inputs
                    if r["object"] in {"build/" + p for p in SPLIT}}
    split = {}
    for obj, tag in SPLIT.items():
        path = str((BASE / "build") / obj)
        funcs = function_sections(objects[path], tag)
        split[path] = funcs
        split_assembly(tag, funcs)

    # These callbacks differ only in the unused-in-the-lambda Submit template
    # argument. GCC changed which instance receives which inlining decisions.
    # PRE's 824-byte body cannot fit POST's 544-byte slot. Preserve the two actual
    # instruction bodies at POST's corresponding body slots; retain PRE symbols
    # and call targets. This is recorded as two name-placement exceptions.
    swap = {CALLBACK.format("0"): CALLBACK.format("1"),
            CALLBACK.format("1"): CALLBACK.format("0")}
    planned = []
    exceptions = []
    for entry in pre_inputs:
        obj = entry["object"]
        section = entry["section"]
        original = objects[obj]
        target = post_sections.get((obj, section))
        require(target is not None, f"PRE input section absent in POST: {obj}({section})")
        if obj in split and section in PLAIN:
            suffix = str(Path(obj).relative_to(str(BASE / "build")))
            tag = SPLIT[suffix]
            target_obj = post_objects["build/" + suffix]
            target_syms = {s["name"]: s for s in target_obj.functions(section)}
            seen = set()
            for sym in original.functions(section):
                name, size = split[obj][sym["name"]]
                if name in seen:
                    continue
                seen.add(name)
                other = target_syms[sym["name"]]
                address = target["address"] + other["address"]
                # PRE's preceding cold cleanup is three bytes larger. Keep the
                # final cold boot fragment at +3; all its instructions survive.
                if section == ".text.unlikely" and sym["name"].startswith("_ZN4tomo27run_split_read_local_server"):
                    address += 3
                    exceptions.append(dict(name=sym["name"], post_address=target["address"] + other["address"],
                                           pad_address=address, reason="PRE preceding cold fragment is 3 bytes larger"))
                planned.append(dict(address=address, size=size, object=str(OUT / f"{tag}.o"),
                                    section=name, pre_object=obj, pre_section=section, name=sym["name"]))
        else:
            address = target["address"]
            symbol = section.removeprefix(".text.")
            if symbol in swap:
                address = post_sections[(obj, ".text." + swap[symbol])]["address"]
                exceptions.append(dict(name=symbol, post_address=target["address"], pad_address=address,
                                       reason="preserve equivalent instruction-body placement across GCC callback swap"))
            tag = SPLIT.get(str(Path(obj).relative_to(str(BASE / "build")))) if obj.startswith(str(BASE / "build") + "/") else None
            planned.append(dict(address=address, size=entry["size"],
                                object=str(OUT / f"{tag}.o") if tag else obj,
                                section=section, pre_object=obj, pre_section=section))

    planned.sort(key=lambda r: r["address"])
    previous_end = post.sections[".text"]["address"]
    for row in planned:
        require(row["address"] >= previous_end, f"overlapping PRE body slot: {row}")
        previous_end = row["address"] + row["size"]
    text = post.sections[".text"]
    require(previous_end == text["address"] + text["size"], "last section must end exactly at POST text end")
    body = [f"  .text {text['address']:#x} :\n  {{\n    FILL(0x90909090)\n"]
    for row in planned:
        body.append(f"    . = {row['address'] - text['address']:#x};\n")
        body.append(f"    {row['object']}({row['section']})\n")
    body.append(f"    . = {text['size']:#x};\n  }}\n")
    # Use the system's PIE script, preserving dynamic linking and unwind handling.
    default = run("ld", "-pie", "-z", "now", "-z", "relro", "--verbose").split("==================================================")[1]
    script, count = re.subn(r"  \.text\s*:\s*\{.*?\n  \}\n", "".join(body), default, count=1, flags=re.S)
    require(count == 1, "cannot find default text output section")
    (OUT / "placement.ld").write_text(script)
    manifest = dict(kind="A behaviour twin", exact_post_placement=False, exceptions=exceptions,
                    pre_sha256=PRE_SHA, post_sha256=POST_SHA, post_text=text,
                    sections=planned)
    (OUT / "layout.json").write_text(json.dumps(manifest, indent=2) + "\n")

    argv = json.loads((OUT / "pre-link.json").read_text())
    for obj, tag in SPLIT.items():
        argv[argv.index(str((BASE / "build") / obj))] = str(OUT / f"{tag}.o")
    argv[argv.index("-o") + 1] = str(CANDIDATE)
    argv += [f"-Wl,-T,{OUT}/placement.ld,-Map={OUT}/pad.map"]
    make = [f"all: {CANDIDATE}\n"]
    for tag in SPLIT.values():
        make.append(f"{OUT}/{tag}.raw.o: {OUT}/{tag}.split.s\n\tgcc -c $< -o $@\n")
        make.append(f"{OUT}/{tag}.o: {OUT}/{tag}.raw.o {OUT}/layout.json tools/reorder_pad.py\n"
                    f"\tpython3 tools/reorder_pad.py trim {tag}\n")
    make.append(f"{CANDIDATE}: {OUT}/main.o {OUT}/rl2s.o {OUT}/placement.ld\n\t" + shlex.join(argv) + "\n")
    (OUT / "pad.mk").write_text("".join(make))
    print(f"planned {len(planned)} input sections; {len(exceptions)} explicit placement exceptions")


def trim():
    tag = sys.argv[2]
    require(tag in SPLIT.values(), "unknown assembly object")
    raw = OUT / f"{tag}.raw.o"
    obj = Elf(raw)
    data = raw.read_bytes()
    planned = json.loads((OUT / "layout.json").read_text())["sections"]
    rewritten = bytearray(data)
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    # Literal branch opcodes make GAS partition a following alignment NOP
    # differently (e.g. 1+3 instead of one 4-byte NOP). Restore PRE's actual NOP
    # bytes only after proving the same complete interval decodes as NOPs in
    # both objects. Every branch, live operand and relocation stays untouched.
    original_path = next((BASE / "build") / p for p, t in SPLIT.items() if t == tag)
    original = Elf(original_path)
    original_data = original_path.read_bytes()

    def nop_ranges(path):
        ranges = collections.defaultdict(list)
        section = None
        for line in run("objdump", "-dw", str(path)).splitlines():
            match = re.fullmatch(r"Disassembly of section (.+):", line)
            if match:
                section = match[1]
            match = re.match(r"\s*([0-9a-f]+):\s*((?:[0-9a-f]{2} )+)\s*(.*)", line)
            if not match:
                continue
            encoded = bytes.fromhex(match[2])
            if not (re.search(r"\bnop[lw]?\b", match[3]) or encoded == b"\x66\x90"):
                continue
            start = int(match[1], 16)
            end = start + len(encoded)
            if ranges[section] and ranges[section][-1][1] == start:
                ranges[section][-1] = (ranges[section][-1][0], end)
            else:
                ranges[section].append((start, end))
        return ranges

    before_nops = nop_ranges(original_path)
    after_nops = nop_ranges(raw)
    new_symbols = {s["name"]: s for s in obj.functions()}
    visited = set()
    nop_fixes = []
    for sym in original.functions():
        old_section = original.by_index[sym["section"]]
        other = new_symbols[sym["name"]]
        new_section = obj.by_index[other["section"]]
        key = (sym["section"], sym["address"])
        if key in visited:
            continue
        visited.add(key)
        require(sym["size"] == other["size"], f"reassembled function size changed: {sym['name']}")
        for begin, end in before_nops[old_section["name"]]:
            if begin < sym["address"] or end > sym["address"] + sym["size"]:
                continue
            target_begin = other["address"] + begin - sym["address"]
            target_end = target_begin + end - begin
            require(any(a <= target_begin and target_end <= b for a, b in after_nops[new_section["name"]]),
                    f"PRE NOP interval is not NOPs after reassembly: {sym['name']}+{begin - sym['address']:x}")
            old_bytes = original_data[old_section["offset"] + begin:old_section["offset"] + end]
            at = new_section["offset"] + target_begin
            if rewritten[at:at + len(old_bytes)] != old_bytes:
                rewritten[at:at + len(old_bytes)] = old_bytes
                nop_fixes.append(dict(name=sym["name"], offset=begin - sym["address"], bytes=len(old_bytes)))
    receipt = []
    for row in planned:
        if row["object"] != str(OUT / f"{tag}.o") or not row["section"].startswith(".text.r2pad."):
            continue
        section = obj.sections[row["section"]]
        require(section["size"] >= row["size"], "split assembly body shrank")
        # The original .align 2 after a cold body now belongs to its own input
        # section. Remove that *external* NOP and let the explicit linker slots
        # own alignment; never insert/delete padding inside a PRE function.
        tail = data[section["offset"] + row["size"]:section["offset"] + section["size"]]
        require(tail in (b"", b"\x90"), f"unexpected trailing bytes: {row['section']}")
        # Change section-header bounds only. objcopy --update-section discards
        # that section's relocation records; retaining them is mandatory here.
        at = header[6] + section["index"] * header[11]
        struct.pack_into("<Q", rewritten, at + 32, row["size"])
        struct.pack_into("<Q", rewritten, at + 48, 1)
        receipt.append(dict(section=row["section"], removed_external_nops=len(tail)))
    (OUT / f"{tag}.o").write_bytes(rewritten)
    (OUT / f"trims-{tag}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (OUT / f"nops-{tag}.json").write_text(json.dumps(nop_fixes, indent=2) + "\n")


def audit():
    # Keep the established address normalizer unchanged. This broader inventory
    # includes cold startup and every other PRE body, not just the 217 hot rows.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    import reorder_noop as checker

    require(sha(PRE) == PRE_SHA and sha(POST) == POST_SHA and sha(COPY) == POST_SHA,
            "an immutable reference changed")
    directory = OUT / "audit"
    directory.mkdir(exist_ok=True)
    checker.self_test()
    pre = checker.Binary(PRE, directory)
    pad = checker.Binary(CANDIDATE, directory)
    candidate = Elf(POST)
    pad_elf = Elf(CANDIDATE)
    require(pad_elf.sections[".text"]["size"] == candidate.sections[".text"]["size"],
            "PAD text size does not match POST")
    require(pad_elf.sections[".text"]["address"] == candidate.sections[".text"]["address"],
            "PAD text start does not match POST")
    require(not any("r2_run" in s["name"] or "drain_tasks_reordered" in s["name"]
                    for s in pad_elf.functions()), "R2 implementation is linked into PAD")
    candidate_functions = collections.defaultdict(list)
    placements = inputs(OUT / "post.map")
    starts = [p["address"] for p in placements]
    # R2 adds local clones with PRE names in its isolated object. They are not
    # replacements for PRE's original clones; match the original object slots.
    symbols = [s for s in candidate.functions()
               if placements[bisect.bisect_right(starts, s["address"]) - 1]["object"] != "build/src/core/reorder.o"]
    decoded = run("c++filt", *(s["name"] for s in symbols)).splitlines()
    by_address = collections.defaultdict(list)
    for symbol, name in zip(symbols, decoded):
        by_address[symbol["address"]].append(checker.canonical(name))
    for address, names in by_address.items():
        candidate_functions[min(names)].append(dict(address=address))
    rows = []
    differences = []
    with (directory / "pre.normalized").open("w") as pre_file, (directory / "pad.normalized").open("w") as pad_file:
        for name in sorted(pre.groups):
            originals = sorted(pre.groups[name], key=lambda r: r["addr"])
            controls = sorted(pad.groups.get(name, []), key=lambda r: r["addr"])
            require(len(originals) == len(controls), f"missing/added PRE clone: {name}")
            targets = sorted(candidate_functions[name], key=lambda r: r["address"])
            require(len(targets) == len(originals), f"missing POST placement reference: {name}")
            for index, (one, other, target) in enumerate(zip(originals, controls, targets)):
                before = [a + " | " + b for a, b in zip(one["ins"], one["encodings"])]
                after = [a + " | " + b for a, b in zip(other["ins"], other["encodings"])]
                equal = before == after and one["size"] == other["size"] and one["aliases"] == other["aliases"]
                heading = f"Function: {name}\nOccurrence: {index}\nSize: {one['size']}\n"
                pre_file.write(heading + "\n".join(before) + "\n")
                pad_file.write(heading + "\n".join(after) + "\n")
                row = dict(name=name, instance=index, aliases=one["aliases"],
                           pre_address=one["addr"], pad_address=other["addr"],
                           post_address=target["address"], bytes=one["size"],
                           pre_instructions=len(before), pad_instructions=len(after), equal=equal,
                           placement_equal=other["addr"] == target["address"],
                           scope=checker.category(name))
                rows.append(row)
                if not equal:
                    import difflib
                    diff = "\n".join(difflib.unified_diff(before, after, fromfile="PRE", tofile="PAD"))
                    differences.append(heading + diff + "\n")
    require(len(rows) == 4882, f"expected 4882 PRE physical bodies, found {len(rows)}")
    require(set(pre.groups) == set(pad.groups), "PAD has added or removed function groups")
    hot = [r for r in rows if r["scope"]]
    require(len(hot) == 217, "established hot inventory changed")
    result = dict(pre_sha256=pre.sha256, pad_sha256=pad.sha256, post_sha256=POST_SHA,
                  text_bytes=candidate.sections[".text"]["size"],
                  functions=len(rows), identical=sum(r["equal"] for r in rows),
                  identical_placement=sum(r["placement_equal"] for r in rows),
                  hot_functions=len(hot), hot_identical=sum(r["equal"] for r in hot),
                  hot_identical_placement=sum(r["placement_equal"] for r in hot), rows=rows)
    (directory / "all-bodies.diff").write_text("".join(differences))
    (directory / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    for row in rows:
        if not row["equal"]:
            print("BODY DIFFERENCE:", row["name"])
    require(not differences, "PRE/PAD body equality failed; do not measure this PAD")
    require(sum(not r["placement_equal"] for r in rows) == 3,
            "placement exceptions differ from the explicit three-slot plan")
    require(all(r["equal"] and r["placement_equal"] for r in hot),
            "an established hot body or its POST placement differs")
    layout = json.loads((OUT / "layout.json").read_text())
    blob = CANDIDATE.read_bytes()
    section = pad_elf.sections[".text"]
    end = section["address"]
    gaps = []
    for row in layout["sections"]:
        count = row["address"] - end
        require(count >= 0, "overlapping PAD input sections")
        if count:
            at = section["offset"] + end - section["address"]
            require(blob[at:at + count] == b"\x90" * count, "non-NOP bytes in a PAD gap")
            gaps.append(dict(address=end, bytes=count))
        end = row["address"] + row["size"]
    require(end == section["address"] + section["size"], "PAD text extends beyond the plan")
    properties = {}
    for arm, binary in [("PRE", PRE), ("PAD", CANDIDATE)]:
        properties[arm] = [line.strip() for line in run("readelf", "-n", str(binary)).splitlines()
                           if any(key in line for key in ["Properties:", "x86 ISA", "OS:"])]
    require(properties["PRE"] == properties["PAD"], "ELF control-flow/ABI properties changed")
    (directory / "gaps-and-properties.json").write_text(json.dumps(dict(gaps=gaps, properties=properties), indent=2) + "\n")
    PAD.write_bytes(CANDIDATE.read_bytes())
    PAD.chmod(CANDIDATE.stat().st_mode)
    require(sha(PAD) == pad.sha256, "published PAD differs from audited candidate")
    print("Published", PAD, pad.sha256)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "layout", "trim", "audit"])
    parser.add_argument("tag", nargs="?")
    args = parser.parse_args()
    if args.action == "trim" and args.tag not in SPLIT.values():
        parser.error("trim requires main or rl2s")
    if args.action != "trim" and args.tag is not None:
        parser.error("only trim accepts an object name")
    require(set(os.sched_getaffinity(0)) <= set(range(112, 128)),
            "run under taskset -c 112-127")
    globals()[args.action]()
