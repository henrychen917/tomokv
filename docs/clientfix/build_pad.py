#!/usr/bin/env python3
"""Kind A: PRE behavior, POST ClimonConn layout, and POST total .text size.

All temporary source and objects stay in this worktree's build/clientfix.
This controls sidecar layout and total text size, not every function address.
"""
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/clientfix'
SOURCE = ROOT / 'build/clientfix/pad-a-source'
BUILD = ROOT / 'build/clientfix/pad-a'
PRE = '5146b78ee89b64748dd46db970efa8086f653fa0'
receipt = dict(kind='A', behavior='PRE', source=PRE, runs=[])


def run(name, argv, cwd=ROOT):
    command = ['taskset', '-c', '112-127', *map(str, argv)]
    path = BUILD / (name + '.log')
    with path.open('w') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    with gzip.open(OUT / (name + '.log.gz'), 'wb') as log:
        log.write(path.read_bytes())
    receipt['runs'].append(dict(command=command, cwd=str(cwd), exit_code=result.returncode))
    assert result.returncode == 0, path.read_text()[-4000:]


def text_size(binary):
    output = subprocess.check_output(['taskset', '-c', '112-127', 'readelf', '-SW', binary], text=True)
    return int(re.search(r'\.text\s+PROGBITS\s+[0-9a-f]+\s+[0-9a-f]+\s+([0-9a-f]+)', output)[1], 16)


assert not SOURCE.exists() and not BUILD.exists(), 'never overwrite a control build'
SOURCE.mkdir(parents=True)
BUILD.mkdir(parents=True)
archive = subprocess.check_output(['taskset', '-c', '112-127', 'git', 'archive', PRE,
                                   'Makefile', 'src', 'third_party'], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as source:
    source.extractall(SOURCE, filter='data')
path = SOURCE / 'src/cmd/climon.inc'
before = path.read_text()
post = (ROOT / 'src/cmd/climon.inc').read_text()
anchor = '        std::vector<std::string> prefixes;\n'
assert before.count(anchor) == post.count(anchor) == 1
fields = post.split(anchor, 1)[1].split('\n        bool idle() const', 1)[0]
after = before.replace(anchor, anchor + fields, 1)
path.write_text(after)
(OUT / 'pad-a.patch').write_text(''.join(difflib.unified_diff(
    before.splitlines(True), after.splitlines(True), fromfile='PRE/src/cmd/climon.inc',
    tofile='PAD-A/src/cmd/climon.inc')))
run('pad-a-base-build', ['make', '-j16', f'BUILD_ROOT={BUILD}', 'all'], SOURCE)
base = text_size(BUILD / 'tomokv')
target = text_size(ROOT / 'build/tomokv')
padding = target - base
assert padding >= 0, (base, target)
(BUILD / 'text-pad.S').write_text(
    '.text\n.globl tomo_clientfix_pad_A\n.type tomo_clientfix_pad_A,@function\n'
    'tomo_clientfix_pad_A:\n' + f'.fill {padding},1,0x90\n' +
    '.size tomo_clientfix_pad_A,.-tomo_clientfix_pad_A\n.section .note.GNU-stack,"",@progbits\n')
run('pad-a-padding', ['gcc', '-c', BUILD / 'text-pad.S', '-o', BUILD / 'text-pad.o'])
link_make = SOURCE / 'pad-link.mk'
link_make.write_text('include Makefile\n' + f'LDLIBS += {BUILD}/text-pad.o\n' +
                     f'$(BIN): {BUILD}/text-pad.o\n')
run('pad-a-link', ['make', '-f', 'pad-link.mk', '-j16', f'BUILD_ROOT={BUILD}', 'all'], SOURCE)
actual = text_size(BUILD / 'tomokv')
assert actual == target, (actual, target)
receipt.update(binary=str(BUILD / 'tomokv'),
               sha256=hashlib.sha256((BUILD / 'tomokv').read_bytes()).hexdigest(),
               pre_behavior_text=base, post_text=target, padding_bytes=padding,
               final_text=actual,
               limitation='Matches ClimonConn layout and total .text size, not every function address.')
(OUT / 'pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt), flush=True)
