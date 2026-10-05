#!/usr/bin/env python3
"""Build PAD-B: candidate behaviour plus inert text restoring PRE's text size.

Uses the recorded production link command and existing POST objects, never runs
a server, and refuses growth (padding cannot remove candidate code).
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return len(elf.section_data(elf.names.index(".text")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pre", type=Path)
    parser.add_argument("post", type=Path)
    parser.add_argument("link_log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    wanted, current = text_size(args.pre), text_size(args.post)
    padding = wanted - current
    assert padding > 0, "inverse padding needs a smaller candidate"
    command = [shlex.split(line) for line in args.link_log.read_text().splitlines()
               if " -o " + str(args.post) + " " in line]
    assert len(command) == 1, "one exact production link command required"
    command = command[0]
    index = command.index("-o")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source = args.output.parent / "pad.cc"
    obj = args.output.parent / "pad.o"
    compiler = command[:next(i for i, arg in enumerate(command) if arg.endswith('.o'))]
    for _ in range(3):
        # Compile as C++ with the production target flags so GNU CET/ISA notes
        # match the other objects. A bare assembler object silently removes the
        # binary's IBT PLT, shifting every function before padding even starts.
        source.write_text('asm(R"(\n.section .text\n.type respcompat_inverse_padding,@object\n'
                          'respcompat_inverse_padding:\n'
                          f'.fill {padding},1,0x90\n'
                          '.size respcompat_inverse_padding,.-respcompat_inverse_padding\n'
                          ')");\n')
        subprocess.run([*compiler, "-c", str(source), "-o", str(obj)], check=True)
        link = command[:index] + [str(obj), "-o", str(args.output)] + command[index + 2:]
        subprocess.run(link, check=True)
        actual = text_size(args.output)
        if actual == wanted:
            break
        padding += wanted - actual
        assert padding > 0
    assert text_size(args.output) == wanted, "text-size control did not match PRE"
    before, after = Elf(args.post), Elf(args.output)
    old, new = before.functions(), after.functions()
    assert old.keys() == new.keys(), "padding changed the function inventory"
    assert all((old[name]['value'], old[name]['size']) == (new[name]['value'], new[name]['size'])
               for name in old if before.names[old[name]['sec']] == '.text'), "text function placement moved"
    receipt = dict(kind="B: inverse control", behaviour="POST", padding_bytes=padding,
                   pre_text=wanted, post_text=current, pad_text=text_size(args.output),
                   text_function_addresses_and_sizes_unchanged=True,
                   sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    (args.output.parent / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
