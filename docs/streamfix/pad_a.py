#!/usr/bin/env python3
"""PAD-A: PRE behavior and candidate StreamNode layout, .text origin and total size.

This controls section placement/size, not every function's position or data section placement. The receipt states that limitation rather than implying an
exact per-symbol layout twin.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(96, 112)))
PRE = ROOT / 'build/streamfix/pad-layout-source'
OBJECTS = ROOT / 'build/streamfix/pad-layout-objects'
OUT = ROOT / 'build/streamfix/pad-a'
OUT.mkdir(parents=True, exist_ok=True)


def section(path, name):
    elf = Elf(path)
    item = elf.sections[elf.names.index(name)]
    return dict(address=item[3], size=item[5])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


post = ROOT / 'build/streamfix/post-final/tomokv'
baseline = OBJECTS / 'tomokv'
output = ROOT / 'build/streamfix/PAD-A'
recipes = subprocess.check_output(['make', 'BUILD_ROOT=' + str(OBJECTS), '-n', '-W', str(OBJECTS / 'src/main.o'), 'all'],
                                  cwd=PRE, text=True)
link = shlex.split(next(line for line in recipes.splitlines()
                       if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line))
link = [str(PRE / arg) if arg.startswith('build/') and arg.endswith('.o') else arg for arg in link]
link[link.index('-o') + 1] = str(output)
obj, assembly = OUT / 'padding.o', OUT / 'padding.S'
link.insert(link.index('-o'), str(obj))
wanted, before = section(post, '.text'), section(baseline, '.text')
link += ['-Wl,--section-start=.text=' + hex(wanted['address']), '-Wl,--strip-debug']
padding = wanted['size'] - before['size']
assert padding >= 5
for attempt in range(5):
    assembly.write_text('.text\n.balign 1\n.globl tomo_streamfix_pad_a\n'
        '.type tomo_streamfix_pad_a,@function\ntomo_streamfix_pad_a:\nendbr64\nret\n'
        f'.fill {padding - 5},1,0x90\n.size tomo_streamfix_pad_a,.-tomo_streamfix_pad_a\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.balign 8\n'
        '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n')
    subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
    subprocess.run(link, cwd=PRE, check=True)
    actual = section(output, '.text')
    if actual == wanted:
        break
    assert actual['address'] == wanted['address'], (actual, wanted)
    padding += wanted['size'] - actual['size']
else:
    raise AssertionError((actual, wanted))
report = dict(kind='A: behaviour twin', behavior='PRE 83e0b809d with unused StreamNode members matching the candidate layout',
    matched='POST .text start address and total byte size, StreamNode 120 bytes; layout locks unchanged',
    limitation='Individual function offsets and data sections retain PRE layout; this is not an exact per-symbol/data-layout twin.',
    pre_text=before, post_text=wanted, pad_text=actual, padding_bytes=padding,
    source=assembly.read_text(), link=link,
    inputs=[dict(path=arg, sha256=sha(arg)) for arg in link if arg.endswith('.o')],
    arms={name: dict(path=str(path), sha256=sha(path))
          for name, path in [('PRE', ROOT/'build/streamfix/pre/tomokv'), ('PRE-layout', baseline), ('POST', post), ('PAD-A', output)]})
(ROOT / 'docs/streamfix/pad-a.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report['arms'], indent=2), flush=True)
