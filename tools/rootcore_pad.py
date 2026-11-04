#!/usr/bin/env python3
"""PRE behavior with POST text extent; no server or workload is run."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from lbstall_artifacts import Elf

root = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16, 32))
source = root / 'build/rootcore/pre-source'
objects = root / 'build/rootcore/pre-objects'
out = root / 'build/rootcore'

def sections(path):
    e = Elf(path)
    return {name: dict(address=e.sections[e.names.index(name)][3],
                       size=e.sections[e.names.index(name)][5])
            for name in ('.text', '.plt', '.plt.sec', '.rodata', '.data', '.bss')}

recipe = subprocess.check_output(['make', '-Bn', 'BUILD_ROOT=' + str(objects), 'all'],
                                cwd=source, text=True)
link, = [shlex.split(line) for line in recipe.splitlines()
         if line.startswith('g++ ') and ' -c ' not in line and
         ' -o ' + str(objects / 'tomokv') + ' ' in line]
assembly, obj, binary = [out / name for name in ('pad.S', 'pad.o', 'PAD-A')]
link.insert(link.index('-o'), str(obj))
link[link.index('-o') + 1] = str(binary)
wanted = sections(out / 'POST')
before = sections(out / 'PRE')
# mkdtemp is POST's sole new dynamic import. The unreachable relocation below
# retains its PLT slots, matching the text start as well as its total size.
padding = wanted['.text']['size'] - before['.text']['size']
for attempt in range(8):
    assert padding >= 10
    assembly.write_text(
        '.text\n.globl tomo_rootcore_pad\n.type tomo_rootcore_pad,@function\n'
        'tomo_rootcore_pad:\nendbr64\nret\ncall mkdtemp@PLT\n.fill %d,1,0x90\n'
        '.size tomo_rootcore_pad,.-tomo_rootcore_pad\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.balign 8\n'
        '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n' % (padding - 10))
    subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
    subprocess.run(link, cwd=source, check=True)
    actual = sections(binary)
    if actual['.text'] == wanted['.text']:
        break
    assert actual['.text']['address'] == wanted['.text']['address'], (actual, wanted)
    padding += wanted['.text']['size'] - actual['.text']['size']
assert actual['.text'] == wanted['.text']
report = dict(kind='A: behaviour twin; total-text-size control',
    behavior='Unmodified PRE 7d2f8a205 production objects; unreachable padding and mkdtemp relocation only',
    matched='POST .text start and total size, plus .plt/.plt.sec extents',
    limitation='Individual function placement and data-section layout retain PRE; this is not an exact symbol-placement twin.',
    padding_bytes=padding, PRE=before, POST=wanted, PAD_A=actual,
    sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), link=link)
(root / 'docs/rootcore/pad-a.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'link'}, indent=2), flush=True)
