#!/usr/bin/env python3
"""Build a limited type-A aggregate-text-size control; never execute it."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf

PRE = ROOT / "build/txnorder/pre/tomokv"
POST = ROOT / "build/tomokv"
OUT = ROOT / "build/txnorder/pad-a-size"
DOCS = ROOT / "docs/txnorder/pad-a-size"
OUT.mkdir(exist_ok=True)
DOCS.mkdir(exist_ok=True)


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index(".text")][5]


recipe = subprocess.check_output(["taskset", "-c", "48-63", "make", "-n", "-W",
                                  "build/src/main.o", "build/tomokv"], text=True)
command = shlex.split(next(line for line in recipe.splitlines() if " -o build/tomokv " in line))
command = [str(ROOT / "build/txnorder/pre" / part[6:])
           if part.startswith(("build/src/", "build/db0/src/")) and part.endswith(".o") else part
           for part in command]
command[command.index("-o") + 1] = str(OUT / "tomokv")
command.insert(command.index("-o"), str(OUT / "padding.o"))
target = text_size(POST)
padding = target - text_size(PRE)
assert padding > 0, "aggregate type-A padding cannot shrink PRE"
attempts = []
for attempt in range(4):
    (OUT / "padding.S").write_text('.section .text,"ax",@progbits\n.fill ' + str(padding) +
                                   ',1,0x90\n.section .note.GNU-stack,"",@progbits\n')
    compile_command = ["taskset", "-c", "48-63", "gcc", "-c", str(OUT / "padding.S"), "-o", str(OUT / "padding.o")]
    link_command = ["taskset", "-c", "48-63", *command]
    subprocess.run(compile_command, check=True)
    with (DOCS / f"link-{attempt}.log").open("w") as log:
        subprocess.run(link_command, stdout=log, stderr=subprocess.STDOUT, check=True)
    actual = text_size(OUT / "tomokv")
    attempts.append(dict(padding=padding, text_size=actual, compile=compile_command, link=link_command))
    if actual == target:
        break
    padding += target - actual
    assert padding > 0
assert actual == target
receipt = dict(kind="A: PRE behaviour with matched aggregate POST .text size",
               limits="Diagnostic size control only. Internal function addresses and Server's cold tail are not matched; this is not a full layout twin.",
               attempts=attempts, binaries={str(p.relative_to(ROOT)): dict(
                   sha256=hashlib.sha256(p.read_bytes()).hexdigest(), text_size=text_size(p))
                   for p in (PRE, POST, OUT / "tomokv")})
(DOCS / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt["binaries"], indent=2))
