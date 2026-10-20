#!/usr/bin/env python3
"""PAD A: relink frozen PRE objects with unreachable text padding only."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index(".text")][5]


def functions(path):
    elf = Elf(path)
    # Keep duplicate local names; a dict keyed only by name would hide copies.
    return sorted((s["name"], s["value"], s["size"], s["info"])
                  for s in elf.symbols if s["info"] & 15 == 2 and s["size"]
                  and elf.names[s["sec"]] == ".text")


def main():
    pre = ROOT / "build/ntfix-pre/tomokv"
    post = ROOT / "build/tomokv"
    output = ROOT / "build/tomokv-ntfix-pad-a"
    out = ROOT / "docs/ntfix/ntfix2/pad"
    scratch = ROOT / "build/ntfix2/pad-a"
    scratch.mkdir(parents=True, exist_ok=True)
    command = shlex.split((out / "pre-link.log").read_text())
    command[command.index("-o") + 1] = str(output)
    assembly, obj = scratch / "padding.s", scratch / "padding.o"
    command.insert(command.index("-o"), str(obj))
    target = text_size(post)
    padding = target - text_size(pre)
    assert padding > 0
    # An assembly object without this compiler property silently removes IBT /
    # SHSTK from the entire ELF and changes its PLT. Copy the frozen PRE object's
    # note verbatim; the control must preserve those link properties too.
    source = Elf(ROOT / "build/ntfix-pre/src/core/version.o")
    note = source.section_data(source.names.index(".note.gnu.property"))
    for _ in range(3):
        assembly.write_text(f".text\n.fill {padding},1,0x90\n"
                            '.section .note.GNU-stack,"",@progbits\n'
                            '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
                            ",".join(map(str, note)) + "\n")
        subprocess.run(["taskset", "-c", "96-111", "g++", "-c", str(assembly),
                        "-o", str(obj)], cwd=ROOT, check=True)
        subprocess.run(["taskset", "-c", "96-111", *command], cwd=ROOT, check=True)
        difference = target - text_size(output)
        if not difference:
            break
        padding += difference
        assert padding > 0
    else:
        raise AssertionError("PAD text size did not converge")
    a, b = Elf(pre), Elf(output)
    for name in (".note.gnu.property", ".plt", ".plt.got", ".plt.sec"):
        i, j = a.names.index(name), b.names.index(name)
        assert a.sections[i][3:6] == b.sections[j][3:6], name
        if name == ".note.gnu.property":
            assert a.section_data(i) == b.section_data(j), name
    assert functions(pre) == functions(output), "PRE function placement changed"
    receipt = dict(kind="A: PRE behaviour with POST aggregate .text size",
                   limitation="PRE internal text placement is preserved; POST internal placement is not reproduced.",
                   pre=str(pre), post=str(post), pad=str(output), command=command,
                   pre_text=text_size(pre), post_text=target, pad_text=text_size(output),
                   nop_bytes=padding, pre_text_functions=len(functions(pre)),
                   pre_function_addresses_and_sizes_equal=True,
                   pre_gnu_property_bytes_and_plt_layout_equal=True,
                   sha256={arm: hashlib.sha256(path.read_bytes()).hexdigest()
                           for arm, path in (("pre", pre), ("post", post), ("pad", output))})
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "command"}, indent=2))


if __name__ == "__main__":
    main()
