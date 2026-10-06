#!/usr/bin/env python3
"""PAD A: unchanged PRE objects with unreachable padding matching POST .text size.

This controls aggregate .text size, NOT every function's position. No server is run.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
sys.path.insert(0, 'tools')
from lbstall_artifacts import Elf

pre = Path('build/at15-pre/tomokv')
post = Path('build/at15-post')
pad = Path('build/at15-pad-a')

def section_size(path, name):
    elf = Elf(path)
    return elf.sections[elf.names.index(name)][5]

wanted = section_size(post, '.text')
base = section_size(pre, '.text')
assert wanted >= base, 'this control pads a growing candidate'
line = next(line for line in reversed(Path('build/at15/pre-build.log').read_text().splitlines())
            if ' -o build/tomokv ' in line)
command = shlex.split(line)
command = [word.replace('build/db0/', 'build/at15-pre/db0/').replace('build/src/', 'build/at15-pre/src/')
           for word in command]
command[command.index('-o') + 1] = str(pad)
# Insert after all original text, so every PRE input object remains untouched and in its original order.
command.insert(command.index('-o'), 'build/at15/padding.o')
amount = wanted - base
for attempt in range(3):
    source = Path('build/at15/padding.S')
    source.write_text('.section .text\n.balign 1\n.space %d, 0x90\n.section .note.GNU-stack,"",@progbits\n' % amount)
    subprocess.run(['g++', '-c', str(source), '-o', 'build/at15/padding.o'], check=True)
    subprocess.run(command, check=True)
    actual = section_size(pad, '.text')
    if actual == wanted:
        break
    amount += wanted - actual
    assert amount >= 0
else:
    raise AssertionError('could not match .text size')
receipt = dict(kind='A: behaviour twin; aggregate .text-size control',
               limitation='PRE behaviour and identical input objects; per-function POST placement is not reproduced',
               pre_text_section=base, post_text_section=wanted, pad_text_section=actual,
               unreachable_padding_bytes=amount, command=command,
               sha256=hashlib.sha256(pad.read_bytes()).hexdigest())
Path('docs/at15/pad-a.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({key:value for key,value in receipt.items() if key != 'command'}, indent=2))
