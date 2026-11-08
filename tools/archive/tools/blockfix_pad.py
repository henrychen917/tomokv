#!/usr/bin/env python3
"""Link a PRE-behaviour PAD-A control with POST's total .text size, without running it."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/blockfix/PRE"
OUT = ROOT / "build/blockfix/PAD-A"


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index(".text")][5]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = subprocess.check_output(["make", "-Bn", "all"], cwd=ROOT, text=True)
    command = next(shlex.split(line) for line in reversed(plan.splitlines())
                   if " -o build/tomokv " in line)
    original = command.copy()
    for i, arg in enumerate(command):
        if arg.startswith(("build/src/cmd/", "build/db0/src/cmd/")) and Path(arg).stem in (
                "xshard", "t_stream", "t_stream_groups", "t_string"):
            command[i] = str(BASE / Path(arg).relative_to("build"))
    command[command.index("-o") + 1] = str(OUT / "tomokv")
    subprocess.run(command, cwd=ROOT, check=True)
    base_text = text_size(OUT / "tomokv")
    assert base_text == text_size(BASE / "tomokv"), "PRE object reconstruction text drift"
    post_text = text_size(ROOT / "build/tomokv")
    padding = post_text - base_text
    assert padding >= 0, "candidate shrank: this PAD-A constructor needs a new control"
    assembly = OUT / "padding.s"
    # An assembly object without the compiler's CET property makes ld discard
    # .plt.sec for the WHOLE executable. Preserve the input note verbatim: a
    # padding control must not also change indirect-call protection/PLT layout.
    reference = Elf(BASE / "src/cmd/xshard.o")
    note = reference.sections[reference.names.index(".note.gnu.property")]
    properties = reference.data[note[4]:note[4]+note[5]]
    assembly.write_text('.section .text.blockfix_pad_a,"ax",@progbits\n'
                        '.globl blockfix_pad_a\n.type blockfix_pad_a,@function\n'
                        f'blockfix_pad_a:\n.fill {padding},1,0x90\n'
                        '.size blockfix_pad_a,.-blockfix_pad_a\n'
                        '.section .note.GNU-stack,"",@progbits\n'
                        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
                        ','.join(str(byte) for byte in properties) + '\n')
    subprocess.run(["gcc", "-c", str(assembly), "-o", str(OUT / "padding.o")], check=True)
    command.insert(command.index("-o"), str(OUT / "padding.o"))
    subprocess.run(command, cwd=ROOT, check=True)
    assert text_size(OUT / "tomokv") == post_text
    arms = {}
    layout = {}
    for name, path in (("PRE", BASE / "tomokv"), ("POST", ROOT / "build/tomokv"),
                       ("PAD-A", OUT / "tomokv")):
        arms[name] = dict(path=str(path.relative_to(ROOT)), text_bytes=text_size(path),
                         sha256=hashlib.file_digest(path.open("rb"), "sha256").hexdigest())
        elf = Elf(path)
        layout[name] = {section: dict(address=elf.sections[elf.names.index(section)][3],
                                     bytes=elf.sections[elf.names.index(section)][5])
                        for section in ('.text', '.plt', '.plt.sec')}
    assert len({v['.text']['address'] for v in layout.values()}) == 1
    assert layout['PRE']['.plt'] == layout['POST']['.plt'] == layout['PAD-A']['.plt']
    assert layout['PRE']['.plt.sec'] == layout['POST']['.plt.sec'] == layout['PAD-A']['.plt.sec']
    report = dict(kind="A: behaviour twin", padding_bytes=padding,
                  limitation="Matches total .text size, not every function address or internal alignment.",
                  production_link=original, pad_link=command, arms=arms, elf_layout=layout)
    (ROOT / "docs/blockfix/binary-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(arms, indent=2))


if __name__ == "__main__":
    main()
