#!/usr/bin/env python3
"""Classify ccfix_audit's changed bodies by what actually differs in their instructions.

For each changed (object, symbol) pair, both bodies are disassembled from the objects and
compared after removing addresses and turning branch targets into body-relative offsets.
`cc-only`: equal once each conditional mnemonic is replaced by its strict/non-strict family
(jl/jle, jg/jge, jb/jbe, ja/jae, setl/setle, cmovl/cmovle, ...), i.e. the same instructions with
only `<` versus `<=` flipped. `immediate`: additionally differs only in immediates/displacements.
`code`: anything else (layout, inlining, register allocation). Sizes come from the audit.

usage: cc_classify.py <changed-bodies.json> <reference-build-root> <candidate-build-root> <out.json>
"""
import collections
import json
from pathlib import Path
import re
import subprocess
import sys

FAMILY = {}
for group in ("l le", "g ge", "b be", "a ae", "nl nle", "ng nge", "nb nbe", "na nae"):
    a, b = group.split()
    for prefix in ("j", "set", "cmov"):
        FAMILY[prefix + a] = FAMILY[prefix + b] = prefix + a + "|" + b


def bodies(path):
    # Only FUNC symbols start a body: local NOTYPE labels (e.g. layout pads) sit inside one.
    symbols = subprocess.check_output(["readelf", "-sW", str(path)], text=True, errors="replace")
    functions = {f[7] for f in (line.split() for line in symbols.splitlines())
                 if len(f) >= 8 and f[3] == "FUNC"}
    out = subprocess.check_output(["objdump", "-dw", "--no-show-raw-insn", "-r", str(path)],
                                  text=True, errors="replace")
    result, name, rows = {}, None, []
    for line in out.splitlines():
        head = re.fullmatch(r"([0-9a-f]+) <(.+)>:", line)
        if line.startswith("Disassembly of section "):
            if name:
                result[name] = rows
            name, rows = None, []
            continue
        if head and head[2] in functions:
            if name:
                result[name] = rows
            name, rows = head[2], []
            base = int(head[1], 16)
            continue
        if head:
            continue
        if name is None:
            continue
        reloc = re.match(r"\s+[0-9a-f]+: (R_\S+)\s+(\S+)", line)
        if reloc:
            rows.append(("reloc", reloc[1], re.sub(r"[-+]0x[0-9a-f]+$", "", reloc[2])))
            continue
        ins = re.match(r"\s*([0-9a-f]+):\s+(.*)", line)
        if ins:
            text = ins[2].split("#")[0].strip()
            target = re.match(r"(\S+)\s+([0-9a-f]+) <", text)
            if target and target[1].startswith(("j", "call")) and "<" in text:
                symbol = re.search(r"<([^>+]+)", text)[1]
                offset = int(target[2], 16) - base
                # Same-section targets are body-relative; relocated ones keep the target name.
                text = f"{target[1]} <{symbol}>" if symbol in functions and symbol != name \
                    else f"{target[1]} .+{offset}"
            rows.append(("ins", text))
    if name:
        result[name] = rows
    return result


def canonical(rows, level):
    out = []
    for row in rows:
        if row[0] == "reloc":
            out.append(row)
            continue
        text = " ".join(row[1].split())
        mnemonic = text.split()[0] if text else text
        if level >= 1 and mnemonic in FAMILY:
            text = FAMILY[mnemonic] + text[len(mnemonic):]
        if level >= 2:
            text = re.sub(r"\$0x[0-9a-f]+|\b0x[0-9a-f]+\b|-?\b\d+\b", "N", text)
        out.append(("ins", text))
    return out


def main():
    changed = json.loads(Path(sys.argv[1]).read_text())
    reference, candidate, destination = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    by_object = collections.defaultdict(list)
    for row in changed:
        by_object[row["object"]].append(row)
    rows = []
    for obj, members in sorted(by_object.items()):
        before, after = bodies(reference / obj), bodies(candidate / obj)
        for row in members:
            a, b = before.get(row["symbol"]), after.get(row["symbol"])
            if a is None or b is None:
                kind = "added" if a is None else "removed"
            elif canonical(a, 0) == canonical(b, 0):
                kind = "identical-text"      # differs only below objdump's view (data/relocs)
            elif canonical(a, 1) == canonical(b, 1):
                kind = "cc-only"
            elif canonical(a, 2) == canonical(b, 2):
                kind = "immediate"
            else:
                kind = "code"
            flips = 0
            if a and b and len(a) == len(b):
                flips = sum(x != y for x, y in zip(a, b) if x[0] == "ins" and y[0] == "ins")
            rows.append(dict(object=obj, name=row["name"], symbol=row["symbol"], kind=kind,
                             pre_size=row["pre_size"], post_size=row["post_size"],
                             differing_instructions=flips))
        print(obj, collections.Counter(r["kind"] for r in rows if r["object"] == obj), flush=True)
    summary = collections.Counter(r["kind"] for r in rows)
    destination.write_text(json.dumps(dict(summary=summary, bodies=rows), indent=1) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
