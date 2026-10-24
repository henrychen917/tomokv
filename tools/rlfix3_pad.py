#!/usr/bin/env python3
"""Build PAD-A: PRE behaviour at POST's exact .text size, from frozen PRE objects.

This controls total text size; it deliberately does not claim that individual
PRE functions have POST addresses. PRE cold INFO/config objects use tighter alignment if POST shrank.
Padding is unreferenced executable NOPs.
Only builds/inspects files; never starts a server or benchmark.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def text_size(path):
    rows = subprocess.check_output(["size", "-A", str(path)], text=True).splitlines()
    return int(next(row.split()[1] for row in rows if row.startswith(".text ")))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pre_source", type=Path)
    p.add_argument("post", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--kind", choices=("A", "B"), default="A")
    args = p.parse_args()
    pre, post, output = args.pre_source.resolve(), args.post.resolve(), args.output.resolve()
    directory = output.parent / ("rlfix3/pad-" + args.kind.lower())
    directory.mkdir(parents=True, exist_ok=True)
    wanted = text_size(post)
    before = text_size(pre / "build/tomokv")
    objects = subprocess.check_output(["make", "-s", "--eval",
        "rlfix3-objects:;@echo $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ)",
        "rlfix3-objects"], cwd=pre, text=True).split()
    objects = [str(pre / name) for name in objects]
    alignment = False
    if wanted < before:
        # These flags change code alignment, not PRE source or behaviour. Both
        # namespace variants keep their original target-specific IPA budgets.
        alignment = True
        compact = directory / "objects"
        selected = ("src/cmd/t_server.o", "db0/src/cmd/t_server.o")
        targets = [str(compact / name) for name in selected]
        flags = "-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread " + \
                "-falign-functions=1 -falign-loops=1 -falign-jumps=1 -falign-labels=1"
        with (directory / "compile.log").open("w") as log:
            subprocess.run(["make", "-j16", f"BUILD_ROOT={compact}", f"CXXFLAGS={flags}", *targets],
                           cwd=pre, stdout=log, stderr=subprocess.STDOUT, check=True)
        replacements = {str(pre / "build" / name): target for name, target in zip(selected, targets)}
        objects = [replacements.get(name, name) for name in objects]
    def link(extra):
        with (directory / "link.log").open("w") as log:
            subprocess.run(["g++", "-pthread", *objects, *extra, "-o", str(output),
                            "-Wl,--wrap=main", "-ljemalloc", "-luring", "-lssl", "-lcrypto", "-lm"],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    link([])
    compact_size = text_size(output)
    padding = wanted - compact_size
    assert padding >= 0, "Cold alignment did not shrink PRE enough for this control"
    source, obj = directory / "pad.S", directory / "pad.o"
    for attempt in range(3):
        source.write_text('.section .text.rlfix3_pad,"ax",@progbits\n'
                          '.globl tomo_rlfix3_pad\n.type tomo_rlfix3_pad,@function\n'
                          f'tomo_rlfix3_pad:\n.fill {padding},1,0x90\n'
                          '.size tomo_rlfix3_pad,.-tomo_rlfix3_pad\n'
                          '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(["g++", "-c", str(source), "-o", str(obj)], check=True)
        link([str(obj)])
        actual = text_size(output)
        if actual == wanted: break
        padding += wanted - actual
        assert padding >= 0
    assert text_size(output) == wanted
    subprocess.run(["strip", "--strip-debug", str(output)], check=True)
    proof = dict(kind="A: behaviour twin" if args.kind == "A" else "B: inverse control",
                 behaviour="PRE 05a5e01a9" if args.kind == "A" else "POST",
                 control="Target total .text size; internal function placement is not matched",
                 cold_alignment_compacted=alignment, compact_text_bytes=compact_size,
                 input_text_bytes=before, target_text_bytes=wanted, pad_text_bytes=text_size(output),
                 nop_bytes=padding, sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (directory / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
