#!/usr/bin/env python3
"""blockwake PAD-A: unmodified PRE behaviour linked to POST's .text extent (kind A, behaviour
twin). Modeled on tools/mset8fix_pad.py. This lane makes no throughput claim, so PAD-A exists only
to show the binary size change is not itself the cause of any POST effect; function placement and
data keep PRE's layout. No server, load or timing is run."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf  # noqa: E402

assert os.sched_getaffinity(0) <= set(range(128))
PRE = ROOT / 'build/blockwake/pre-source'
POST = ROOT / 'build/tomokv'
OUT = ROOT / 'build/blockwake/arms'
OUT.mkdir(parents=True, exist_ok=True)


def extent(path):
    elf = Elf(path)
    section = elf.sections[elf.names.index('.text')]
    return dict(address=section[3], size=section[5])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


objects = PRE / 'build'
recipe = subprocess.check_output(['make', '-C', str(PRE), 'BUILD_ROOT=' + str(objects),
    '-n', '-W', str(objects / 'src/main.o'), 'all'], text=True)
link = shlex.split(next(line for line in recipe.splitlines()
                        if ' -o ' + str(objects / 'tomokv') + ' ' in line))
target = OUT / 'tomokv-PAD-A'
link[link.index('-o') + 1] = str(target)
obj = OUT / 'padding.o'
link.insert(link.index('-o'), str(obj))
wanted, original = extent(POST), extent(objects / 'tomokv')
link += ['-Wl,--section-start=.text=' + hex(wanted['address'])]
padding = wanted['size'] - original['size']
for attempt in range(5):
    assert padding >= 5, 'POST is too small for this additive PAD-A'
    assembly = OUT / 'padding.S'
    assembly.write_text('.text\n.globl tomo_blockwake_pad\n.type tomo_blockwake_pad,@function\n'
        'tomo_blockwake_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
        '.size tomo_blockwake_pad,.-tomo_blockwake_pad\n.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.balign 8\n.long 4,16,5\n.asciz "GNU"\n'
        '.long 0xc0000002,4,3,0\n' % (padding - 5))
    subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
    subprocess.run(link, cwd=PRE, check=True)
    actual = extent(target)
    if actual == wanted:
        break
    assert actual['address'] == wanted['address'], (actual, wanted)
    padding += wanted['size'] - actual['size']
assert actual == wanted, (actual, wanted)
shutil.copy2(objects / 'tomokv', OUT / 'tomokv-PRE')
shutil.copy2(POST, OUT / 'tomokv-POST')
record = dict(kind='A: behaviour twin', behavior='PRE 8be4f68323 (wave 15)',
              matched='POST .text start and total size', text=wanted, padding=padding,
              limitation='Size control only: internal function placement and data sections retain '
                         'PRE layout. Not an exact symbol-layout twin.',
              link=link, arms={})
for name in ('PRE', 'POST', 'PAD-A'):
    path = OUT / ('tomokv-' + name)
    record['arms'][name] = dict(path=str(path), sha256=sha(path), text=extent(path))
(ROOT / 'build/blockwake/arms.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record['arms'], indent=2))
