#!/usr/bin/env python3
"""Link a type-A aggregate-text-size control from the unchanged merged PRE objects.

This controls total .text size, not internal function placement or Server's
cold-tail layout. It is insufficient to accept a candidate that fails a static
instruction bar. No server or workload is started.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def text_size(path):
    sections = subprocess.check_output(['readelf', '-SW', str(path)], text=True)
    match = re.search(r'\]\s+\.text\s+\w+\s+[0-9a-f]+\s+[0-9a-f]+\s+([0-9a-f]+)', sections)
    return int(match.group(1), 16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/txnfix2/pad'))
    parser.add_argument('--receipt', type=Path, default=Path('docs/txnfix/txnfix2/pad'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    pre = root / 'build/txnfix2/pre/tomokv'
    post = root / 'build/tomokv'
    out = root / args.output
    receipts = root / args.receipt
    out.mkdir(exist_ok=True)
    receipts.mkdir(exist_ok=True)
    lines = (root / 'build/txnfix2/pre-build.log').read_text().splitlines()
    recipe = next(line for line in lines if ' -o ' + str(pre) + ' ' in line)
    command = shlex.split(recipe)
    command[command.index('-o') + 1] = str(out / 'tomokv')
    command.insert(command.index('-o'), str(out / 'padding.o'))
    target = text_size(post)
    padding = target - text_size(pre)
    assert padding > 0
    attempts = []
    for attempt in range(4):
        source = '.section .text,"ax",@progbits\n.fill ' + str(padding) + ',1,0x90\n.section .note.GNU-stack,"",@progbits\n'
        (out / 'padding.S').write_text(source)
        compile_command = ['taskset', '-c', '112-127', 'gcc', '-c', str(out / 'padding.S'), '-o', str(out / 'padding.o')]
        subprocess.run(compile_command, check=True)
        link_command = ['taskset', '-c', '112-127', *command]
        with (receipts / f'link-{attempt}.log').open('w') as log:
            subprocess.run(link_command, cwd=root / 'build/txnfix2/pre-source',
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        actual = text_size(out / 'tomokv')
        attempts.append(dict(padding=padding, text_size=actual, compile=compile_command, link=link_command))
        if actual == target:
            break
        padding += target - actual
        assert padding > 0
    assert actual == target
    receipt = dict(kind='A: PRE behaviour, matched aggregate .text size',
                   limits='Does not reproduce internal function placement or appended Server cold-tail layout; not a full layout twin.',
                   attempts=attempts, binaries={str(p.relative_to(root)): dict(
                       sha256=hashlib.sha256(p.read_bytes()).hexdigest(), text_size=text_size(p))
                       for p in (pre, post, out / 'tomokv')})
    (receipts / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['binaries'], indent=2))


if __name__ == '__main__':
    main()
