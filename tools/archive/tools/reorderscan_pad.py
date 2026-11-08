#!/usr/bin/env python3
"""Build a kind-A text-size control from frozen PRE objects; never run a server.

PRE behaviour, POST aggregate .text size. Internal R7 function addresses are
not matched: this controls total text growth, not every code-placement effect.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('pre_build_log', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert args.output.resolve() not in (args.pre.resolve(), args.post.resolve())
    target = text_size(args.post)
    padding = target - text_size(args.pre)
    assert padding > 0, 'this control is for a candidate that grew .text'
    # Preserve the frozen PRE object's original order and linker flags.
    links = [shlex.split(line) for line in args.pre_build_log.read_text().splitlines()
             if ' -o ' + str(args.pre) + ' ' in line]
    assert len(links) == 1, 'one original PRE link command required'
    command = links[0]
    at = command.index('-o')
    assert command[at + 1] == str(args.pre)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    assembly = args.output.parent / 'padding.s'
    obj = args.output.parent / 'padding.o'
    command[at + 1] = str(args.output)
    command.insert(at, str(obj))
    for _ in range(3):
        assembly.write_text(f'.text\n.fill {padding}, 1, 0x90\n'
                            '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run([command[0], '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(command, check=True)
        difference = target - text_size(args.output)
        if not difference:
            break
        padding += difference
        assert padding > 0
    else:
        raise AssertionError('failed to match .text size')
    receipt = dict(kind='A: PRE behaviour with POST aggregate .text size',
                   limitation='Internal R7 addresses are not matched; this is a size control.',
                   pre=str(args.pre), post=str(args.post), pad=str(args.output),
                   pre_text=text_size(args.pre), post_text=target,
                   pad_text=text_size(args.output), nop_bytes=padding,
                   sha256={arm: hashlib.sha256(path.read_bytes()).hexdigest()
                           for arm, path in [('pre', args.pre), ('post', args.post), ('pad', args.output)]})
    (args.output.parent / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
