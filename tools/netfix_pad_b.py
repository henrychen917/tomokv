#!/usr/bin/env python3
"""PAD-B inverse control: candidate behavior, PRE's exact .text size."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def text_size(binary):
    return next(int(line.split()[1]) for line in subprocess.check_output(
        ['size', '-A', str(binary)], text=True).splitlines() if line.startswith('.text '))


def main():
    root = Path(__file__).resolve().parents[1]
    pre, post = root / 'build/tomokv-pre-netfix', root / 'build/tomokv'
    pad = root / 'build/tomokv-pad-b-netfix'
    assembly, obj = root / 'build/netfix-pad-b.s', root / 'build/netfix-pad-b.o'
    command = next(shlex.split(line) for line in subprocess.check_output(
        ['make', '-n', '-W', 'build/src/main.o', 'build/tomokv'], cwd=root,
        text=True).splitlines() if ' -o build/tomokv ' in line)
    command[command.index('-o') + 1] = str(pad)
    command.insert(command.index('-o'), str(obj))
    target, original = text_size(pre), text_size(post)
    padding = target - original
    assert padding > 256, 'inverse size control is only justified for substantial text shrink'
    for attempt in range(3):
        assembly.write_text('.section .text.netfix_size_pad,"ax",@progbits\n'
            '.global tomo_netfix_inverse_pad\n.type tomo_netfix_inverse_pad,@function\n'
            f'tomo_netfix_inverse_pad:\n.fill {padding},1,0x90\n'
            '.size tomo_netfix_inverse_pad,.-tomo_netfix_inverse_pad\n'
            '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['gcc', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(command, cwd=root, check=True)
        actual = text_size(pad)
        if actual == target:
            break
        padding += target - actual
    assert text_size(pad) == target
    receipt = dict(kind='B: inverse control', pre_text=target, post_text=original,
                   pad_text=text_size(pad), padding_bytes=padding, link_command=command,
                   post_sha256=hashlib.sha256(post.read_bytes()).hexdigest(),
                   pad_sha256=hashlib.sha256(pad.read_bytes()).hexdigest())
    (root / 'docs/netfix/pad-b.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assembly.unlink()
    obj.unlink()


if __name__ == '__main__':
    main()
