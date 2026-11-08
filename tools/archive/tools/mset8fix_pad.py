#!/usr/bin/env python3
"""mset8fix PAD-A: unmodified PRE behaviour with POST's total .text extent. No workload.

Built the way tools/cfgfix2_pad.py built cfgfix2's PAD-A: link the PRE objects (84642b620c) with
one padding object, placing .text at POST's start, and grow the padding until .text matches
POST's start and size exactly. Kind A (behaviour twin): a real POST change shows POST moving while
PAD-A stays with PRE. Size control only: function placement and data keep PRE's layout.
"""
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

# CPUs 112-127 until the maintainer's 'box free' (2026-11-04 04:39), then any of 0-127.
assert os.sched_getaffinity(0) <= set(range(128))
PRE = ROOT / 'build/mset8fix/pre-source'
POST = ROOT / 'build/tomokv'
OUT = ROOT / 'build/mset8fix/arms'
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
link = shlex.split(next(line for line in recipe.splitlines() if ' -o ' + str(objects / 'tomokv') + ' ' in line))
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
    assembly.write_text('.text\n.globl tomo_mset8fix_pad\n.type tomo_mset8fix_pad,@function\n'
        'tomo_mset8fix_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
        '.size tomo_mset8fix_pad,.-tomo_mset8fix_pad\n.section .note.GNU-stack,"",@progbits\n'
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
record = dict(kind='A: behaviour twin', behavior='PRE 84642b620c30fa724f0a6f3adb670f767bf16440',
              matched='POST .text start and total size', text=wanted, padding=padding,
              limitation='Size control only: internal function placement and data sections retain '
                         'PRE layout. This is not an exact symbol-layout twin.',
              link=link, arms={})
for name in ('PRE', 'POST', 'PAD-A'):
    path = OUT / ('tomokv-' + name)
    record['arms'][name] = dict(path=str(path), sha256=sha(path), text=extent(path))
(ROOT / 'docs/mset8fix/arms.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record['arms'], indent=2))
