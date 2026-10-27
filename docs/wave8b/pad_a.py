#!/usr/bin/env python3
"""PAD-A: wave-8 PRE behavior with merged .text origin and total size.

This controls section placement/size, not every function's position or the lazy
log data structures. The receipt states that limitation rather than implying an
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
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 80)))
PRE = ROOT / 'build/wave8b/pre-source'
OUT = ROOT / 'build/wave8b/pad-a'
OUT.mkdir(parents=True, exist_ok=True)


def section(path, name):
    elf = Elf(path)
    item = elf.sections[elf.names.index(name)]
    return dict(address=item[3], size=item[5])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


post = ROOT / 'build/tomokv'
baseline = PRE / 'build/tomokv'
output = ROOT / 'build/tomokv-wave8b-PAD-A'
recipes = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'],
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
    assembly.write_text('.text\n.balign 1\n.globl tomo_wave8b_pad_a\n'
        '.type tomo_wave8b_pad_a,@function\ntomo_wave8b_pad_a:\nendbr64\nret\n'
        f'.fill {padding - 5},1,0x90\n.size tomo_wave8b_pad_a,.-tomo_wave8b_pad_a\n'
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
report = dict(kind='A: behaviour twin', behavior='unmodified wave-8 integration 83e0b809d',
    matched='POST .text start address and total byte size; layout locks unchanged',
    limitation='Individual function offsets and data sections retain PRE layout; this is not an exact per-symbol/data-layout twin.',
    pre_text=before, post_text=wanted, pad_text=actual, padding_bytes=padding,
    source=assembly.read_text(), link=link,
    inputs=[dict(path=arg, sha256=sha(arg)) for arg in link if arg.endswith('.o')],
    arms={name: dict(path=str(path), sha256=sha(path))
          for name, path in [('PRE', baseline), ('POST', post), ('PAD-A', output)]})
(ROOT / 'docs/wave8b/pad-a.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report['arms'], indent=2), flush=True)
