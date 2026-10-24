#!/usr/bin/env python3
"""Build a PRE-behavior, POST-text-size PAD-A; never run a workload.

This is a total-text-size control, not an exact function-placement twin. All
executable behavior comes from the unmodified PRE source, including eager log
allocation. The report preserves that limitation explicitly.
"""
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BASE = 'ef5204b2e9650693228cc105b34625516898b82d'


def section(path, name):
    elf = Elf(path)
    item = elf.sections[elf.names.index(name)]
    return dict(address=item[3], size=item[5])


def main():
    source = ROOT / 'build/serverfix/pad-source'
    objects = ROOT / 'build/serverfix/pad-objects'
    output = ROOT / 'build/tomokv-serverfix-pad-a'
    source.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(['git', 'archive', BASE, 'src', 'third_party', 'Makefile'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        tree.extractall(source, filter='data')
    build = ['make', 'BUILD_ROOT=' + str(objects)]
    subprocess.run([*build, '-j16', 'all'], cwd=source, check=True)
    recipes = subprocess.check_output([*build, '-Bn', 'all'], cwd=source, text=True)
    link, = [shlex.split(line) for line in recipes.splitlines()
             if line.startswith('g++ ') and ' -c ' not in line and ' -o ' + str(objects / 'tomokv') + ' ' in line]
    link[link.index('-o') + 1] = str(output)
    assembly = ROOT / 'build/serverfix/padding.S'
    obj = ROOT / 'build/serverfix/padding.o'
    link.insert(link.index('-o'), str(obj))
    wanted = section(ROOT / 'build/tomokv', '.text')
    unpadded = section(objects / 'tomokv', '.text')
    assert unpadded == section(ROOT / 'build/tomokv-serverfix-pre', '.text'), unpadded
    padding = wanted['size'] - unpadded['size']
    for _ in range(5):
        assert padding >= 5, 'PRE behavior leaves no room for the additive PAD-A'
        assembly.write_text('.text\n.globl tomo_serverfix_text_size_pad\n'
                            '.type tomo_serverfix_text_size_pad,@function\n'
                            'tomo_serverfix_text_size_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
                            '.size tomo_serverfix_text_size_pad,.-tomo_serverfix_text_size_pad\n'
                            '.section .note.GNU-stack,"",@progbits\n'
                            # Preserve the input objects' CET properties, or GNU ld
                            # drops .plt.sec and silently changes the text start.
                            '.section .note.gnu.property,"a",@note\n.balign 8\n'
                            '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n' % (padding - 5))
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(link, cwd=source, check=True)
        actual = section(output, '.text')
        if actual == wanted:
            break
        assert actual['address'] == wanted['address'], (actual, wanted)
        padding += wanted['size'] - actual['size']
    assert actual == wanted, (actual, wanted)
    report = dict(kind='A: behaviour twin', behavior='unmodified PRE ' + BASE,
                  matched='POST .text start address and total byte size',
                  limitation='Function placement and data sections retain PRE behavior/layout; this is not an exact symbol-layout twin.',
                  padding_bytes=padding, text=actual, source_commit=BASE,
                  sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    destination = ROOT / 'docs/serverfix/pad-a.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
