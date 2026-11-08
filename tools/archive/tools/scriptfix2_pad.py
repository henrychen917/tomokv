#!/usr/bin/env python3
"""Relink frozen PRE objects as a size-controlled PAD-A; no workload is run.

This matches POST's .text address/size and imported PLT entries. It does not
claim identical function placement, rodata, or data-section layout.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import io
import tarfile

from latencyfix_pad import section

ROOT = Path(__file__).resolve().parents[1]
BASE = 'a214652ec262aa9a5eeaeadf129c0ef76ba6c99c'


def main():
    source = ROOT / 'build/scriptfix2/pre-source'
    if not source.exists():
        source.mkdir(parents=True)
        archive = subprocess.check_output(['git', 'archive', BASE, 'Makefile', 'src',
                                           'third_party', 'tools', 'tests'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as frozen:
            frozen.extractall(source, filter='data')
    objects = ROOT / 'build/scriptfix2/pre'
    output = ROOT / 'build/scriptfix2/tomokv-pad-a'
    recipes = subprocess.check_output(
        ['make', 'BUILD_ROOT=' + str(objects), '-Bn', 'all'], cwd=source, text=True)
    link, = [shlex.split(line) for line in recipes.splitlines()
             if line.startswith('g++ ') and ' -c ' not in line and
             ' -o ' + str(objects / 'tomokv') + ' ' in line]
    link[link.index('-o') + 1] = str(output)
    assembly = ROOT / 'build/scriptfix2/padding.S'
    obj = ROOT / 'build/scriptfix2/padding.o'
    link.insert(link.index('-o'), str(obj))
    wanted = section(ROOT / 'build/tomokv', '.text')
    unpadded = section(objects / 'tomokv', '.text')
    padding = wanted['size'] - unpadded['size']
    # These three imports account for the POST .plt/.plt.sec growth. References
    # live after RET in an unreachable padding symbol, with no initializer.
    prefix = ('.text\n.globl tomo_scriptfix2_text_size_pad\n'
              '.type tomo_scriptfix2_text_size_pad,@function\n'
              'tomo_scriptfix2_text_size_pad:\nendbr64\nret\n'
              'call clock@PLT\ncall flockfile@PLT\ncall funlockfile@PLT\n')
    suffix = ('.size tomo_scriptfix2_text_size_pad,.-tomo_scriptfix2_text_size_pad\n'
              '.section .note.GNU-stack,"",@progbits\n'
              '.section .note.gnu.property,"a",@note\n.balign 8\n'
              '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n')
    for _ in range(5):
        assert padding >= 20
        assembly.write_text(prefix + f'.fill {padding - 20},1,0x90\n' + suffix)
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(link, cwd=source, check=True)
        actual = section(output, '.text')
        if actual == wanted:
            break
        assert actual['address'] == wanted['address'], (actual, wanted)
        padding += wanted['size'] - actual['size']
    assert actual == wanted, (actual, wanted)
    report = dict(kind='A: behaviour twin', behavior='unmodified PRE ' + BASE,
                  matched='POST .text address/size and imported PLT entries',
                  limitation='Not an exact function-placement or data-layout twin.',
                  padding_bytes=padding, pre_text=unpadded, post_text=wanted,
                  pad_text=actual, source_commit=BASE,
                  sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (ROOT / 'docs/scriptfix2/pad-a.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
