#!/usr/bin/env python3
"""PAD-A (A: behaviour twin): unmodified PRE objects plus padding to POST's .text.

Links build/scriptfix4/pre's PRE objects with one padding function so the .text start
address and total size equal the POST arm's. Never runs a workload. This controls total
text size; function placement, data and BSS keep PRE's layout (reported, not hidden).
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'build/scriptfix4/pre-source'
OBJECTS = ROOT / 'build/scriptfix4/pre'
OUT = ROOT / 'build/scriptfix4'


def section(path, name):
    elf = Elf(path)
    item = elf.sections[elf.names.index(name)]
    return dict(address=item[3], size=item[5])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--post', type=Path, default=OUT / 'POST')
    args = parser.parse_args()
    output = OUT / 'PAD-A'
    recipes = subprocess.check_output(['make', 'BUILD_ROOT=' + str(OBJECTS), '-n', '-W',
                                       str(OBJECTS / 'src/main.o'), 'all'], cwd=SOURCE, text=True)
    link, = [shlex.split(line) for line in recipes.splitlines()
             if line.startswith('g++ ') and ' -c ' not in line and
             ' -o ' + str(OBJECTS / 'tomokv') + ' ' in line]
    link[link.index('-o') + 1] = str(output)
    assembly = OUT / 'pad-a.S'
    obj = OUT / 'pad-a.o'
    link.insert(link.index('-o'), str(obj))
    wanted = section(args.post, '.text')
    pre = section(OBJECTS / 'tomokv', '.text')
    padding = wanted['size'] - pre['size']
    actual = None
    for _ in range(6):
        assert padding >= 5, ('PRE behaviour leaves no room for an additive PAD-A', padding)
        assembly.write_text('.text\n.globl tomo_scriptfix4_text_size_pad\n'
                            '.type tomo_scriptfix4_text_size_pad,@function\n'
                            'tomo_scriptfix4_text_size_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
                            '.size tomo_scriptfix4_text_size_pad,.-tomo_scriptfix4_text_size_pad\n'
                            '.section .note.GNU-stack,"",@progbits\n'
                            # Keep the inputs' CET property, or GNU ld drops .plt.sec and
                            # silently moves the text start.
                            '.section .note.gnu.property,"a",@note\n.balign 8\n'
                            '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n' % (padding - 5))
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(link, cwd=SOURCE, check=True)
        actual = section(output, '.text')
        if actual == wanted:
            break
        assert actual['address'] == wanted['address'], (actual, wanted)
        padding += wanted['size'] - actual['size']
    assert actual == wanted, (actual, wanted)
    arms = {}
    for arm, path in (('PRE', OBJECTS / 'tomokv'), ('POST', args.post), ('PAD-A', output)):
        elf = Elf(path)
        arms[arm] = dict(path=str(Path(path).resolve().relative_to(ROOT)), sha256=sha(path),
                         sections={name: elf.sections[elf.names.index(name)][5]
                                   for name in ('.text', '.data', '.bss', '.tbss')
                                   if name in elf.names})
    report = dict(kind='A: behaviour twin', behaviour='unmodified PRE 9d6ab5526 objects',
                  matched='POST .text start address and total byte size',
                  limitation='Function placement, data, BSS and TLS keep PRE layout; '
                             'not an exact symbol-layout twin.',
                  padding_bytes=padding, link=link, arms=arms)
    (ROOT / 'docs/scriptfix4/pad-a.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['arms'], indent=2), flush=True)


if __name__ == '__main__':
    main()
