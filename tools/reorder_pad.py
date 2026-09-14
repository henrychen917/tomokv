#!/usr/bin/env python3
"""Build the R7 PRE-behaviour placement control without running an executable.

The measured POST is an immutable input. Reuse PRE release objects, split only
the two changed translation units' existing assembly into linkable functions,
and let ld fill unused POST slots with unreachable NOPs. A full linked-body audit
is required: a successful link alone is not evidence of a behaviour twin.
"""

import argparse
import collections
import hashlib
import json
import re
import shlex
import struct
import subprocess
from pathlib import Path

PRE_SHA = "2f77224583b7c6ad2423f055a6319a3150a9694fca28068bc615c0e97f757278"
POST_SHA = "6cc7999384990bfdd4af4817042eca851af7a7048dd61eba6ad2a2a0d1d77a25"
PRE = Path("build/r7-pre/build/tomokv")
POST = Path("build/tomokv")
OUT = Path("build/r7-pad")
PAD = Path("build/tomokv-r7-pad")
COPY = Path("build/tomokv-r7-post-v2")
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
        return str(Path("build/r7-pre") / post_object)
    return post_object


def function_sections(obj, tag):
    result = {}
    for section in sorted(PLAIN):
        for sym in obj.functions(section):
            # Aliases at one address share one section and one physical body.
            name = f".text.r7pad.{tag}.{sym['section']}.{sym['address']:x}"
            result[sym["name"]] = (name, sym["size"])
    return result


def split_assembly(tag, funcs):
    """Change section directives and ELF sizes only; preserve all instructions.

    GCC returns to .text before emitting a hot function's .size after its cold
    fragment. Use PRE's size metadata because each fragment now has its own input
    section. The independent audit checks real decoded bytes and widths too.
    """
    source = OUT / f"{tag}.s"
    target = OUT / f"{tag}.split.s"
    found = set()
    current = {}
    original_section = ".text"
    with source.open() as src, target.open("w") as dst:
        for line in src:
            directive = re.match(r'\s*\.section\s+([^,\s]+)', line)
            if line.strip() == ".text" or directive:
                original_section = directive[1] if directive else ".text"
                if original_section in current:
                    line = f'\t.section {current[original_section]},"ax",@progbits\n'
            label = line.rstrip().removesuffix(":")
            if line.endswith(":\n") and label in funcs:
                section, _ = funcs[label]
                require(original_section in PLAIN, f"unexpected original function section: {label}")
                current[original_section] = section
                dst.write(f'\t.section {section},"ax",@progbits\n')
                found.add(label)
            match = re.fullmatch(r"\s*\.size\s+([^,]+),\s*\.\s*-\s*\1\s*", line)
            if match and match[1] in funcs:
                line = f"\t.size {match[1]}, {funcs[match[1]][1]}\n"
            dst.write(line)
    # Constructor/destructor .set aliases do not have a separate label.
    require(found, f"no functions split in {source}")
    return target


def prepare():
    require(sha(PRE) == PRE_SHA and sha(POST) == POST_SHA, "reference binary SHA changed")
    OUT.mkdir(exist_ok=True, parents=True)
    if COPY.exists():
        require(COPY.read_bytes() == POST.read_bytes(), "POST-v2 copy has different bytes")
    else:
        COPY.write_bytes(POST.read_bytes())
        COPY.chmod(POST.stat().st_mode)

    old_recipe = json.loads(Path("build/r7-noop-v2/pad-recipe.json").read_text())
    pre_argv = [a for a in old_recipe["link_argv"] if not a.endswith("/padding.o")]
    pre_argv[pre_argv.index("-o") + 1] = str(OUT / "pre-layout")
    # Relative object names let the script work in this worktree after relocation.
    root = str(Path.cwd()) + "/"
    pre_argv = [a.removeprefix(root) for a in pre_argv]
    post_argv = shlex.split(Path("build/r7-noop-v2/final-publish-build.log").read_text().splitlines()[-1])
    post_argv[post_argv.index("-o") + 1] = str(OUT / "post-layout")
    recipes = []
    for name, argv in [("pre", pre_argv), ("post", post_argv)]:
        recipes.append(shlex.join(argv + [f"-Wl,-Map={OUT}/{name}.map"]))
    (OUT / "maps.mk").write_text("all:\n" + "".join("\t" + r + "\n" for r in recipes))
    (OUT / "pre-link.json").write_text(json.dumps(pre_argv, indent=2) + "\n")
    subprocess.run(["make", "-j8", "-f", str(OUT / "maps.mk")], check=True)
    require((OUT / "pre-layout").read_bytes() == PRE.read_bytes(), "PRE relink is not reproducible")
    require((OUT / "post-layout").read_bytes() == POST.read_bytes(), "POST relink is not reproducible")


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
        path = str(Path("build/r7-pre/build") / obj)
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
            suffix = str(Path(obj).relative_to("build/r7-pre/build"))
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
            tag = SPLIT.get(str(Path(obj).relative_to("build/r7-pre/build"))) if obj.startswith("build/r7-pre/build/") else None
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
    default = run("ld", "-pie", "--verbose").split("==================================================")[1]
    script, count = re.subn(r"  \.text\s*:\s*\{.*?\n  \}\n", "".join(body), default, count=1, flags=re.S)
    require(count == 1, "cannot find default text output section")
    (OUT / "placement.ld").write_text(script)
    manifest = dict(kind="A behaviour twin", exact_post_placement=False, exceptions=exceptions,
                    pre_sha256=PRE_SHA, post_sha256=POST_SHA, post_text=text,
                    sections=planned)
    (OUT / "layout.json").write_text(json.dumps(manifest, indent=2) + "\n")

    argv = json.loads((OUT / "pre-link.json").read_text())
    for obj, tag in SPLIT.items():
        argv[argv.index(str(Path("build/r7-pre/build") / obj))] = str(OUT / f"{tag}.o")
    argv[argv.index("-o") + 1] = str(PAD)
    argv += [f"-Wl,-T,{OUT}/placement.ld,-Map={OUT}/pad.map"]
    make = [f"all: {PAD}\n"]
    for tag in SPLIT.values():
        make.append(f"{OUT}/{tag}.o: {OUT}/{tag}.split.s\n\tgcc -c $< -o $@\n")
    make.append(f"{PAD}: {OUT}/main.o {OUT}/rl2s.o {OUT}/placement.ld\n\t" + shlex.join(argv) + "\n")
    (OUT / "pad.mk").write_text("".join(make))
    print(f"planned {len(planned)} input sections; {len(exceptions)} explicit placement exceptions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "layout"])
    args = parser.parse_args()
    require(set(__import__("os").sched_getaffinity(0)) <= set(range(112, 128)),
            "run under taskset -c 112-127")
    globals()[args.action]()
