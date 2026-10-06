#!/usr/bin/env python3
"""Freeze POST and a kind-A PRE-behaviour control matching POST's aggregate .text."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, 'tools')
from lbstall_artifacts import Elf

pre = Path('build/at15b-pre/tomokv')
post = Path('build/at15b-post')
pad = Path('build/at15b-pad-a')
shutil.copy2('build/tomokv', post)


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


base, wanted = text_size(pre), text_size(post)
assert wanted >= base, 'kind-A aggregate padding requires a growing candidate'
line = next(line for line in Path('build/at15b-build.log').read_text().splitlines()
            if ' -o build/tomokv ' in line)
command = shlex.split(line)
command = [word.replace('build/db0/', 'build/at15b-pre/db0/').replace(
    'build/src/', 'build/at15b-pre/src/') for word in command]
command[command.index('-o') + 1] = str(pad)
source = Path('build/at15b-padding.S')
obj = source.with_suffix('.o')
command.insert(command.index('-o'), str(obj))
amount = wanted - base
for attempt in range(3):
    source.write_text('.section .text\n.balign 1\n.space %d, 0x90\n'
                      '.section .note.GNU-stack,"",@progbits\n' % amount)
    subprocess.run(['g++', '-c', str(source), '-o', str(obj)], check=True)
    subprocess.run(command, check=True)
    actual = text_size(pad)
    if actual == wanted:
        break
    amount += wanted - actual
    assert amount >= 0
else:
    raise AssertionError('could not match .text size')

receipt = dict(kind='A: behaviour twin', pre_text=base, post_text=wanted, pad_text=actual,
               unreachable_padding_bytes=amount, command=command,
               limitation='Matches aggregate .text size, not per-function POST placement or the cold DatabaseStats table layout',
               sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (pre, post, pad)})
Path('docs/at15b/pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
Path('docs/at15b/SHA256SUMS').write_text(''.join(value + '  ' + key + '\n'
                                                for key, value in receipt['sha256'].items()))
print(json.dumps({key: value for key, value in receipt.items() if key != 'command'}, indent=2))
