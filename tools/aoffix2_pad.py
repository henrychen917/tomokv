#!/usr/bin/env python3
"""PAD A: PRE behavior, POST AOF-only layouts and total linked .text size.

Function addresses may differ. This is a size/layout control, not an assertion
that every linked function occupies the same address. Production has no selector.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'build/aoffix2'
SOURCE, PAD = BASE / 'pad-src', BASE / 'pad'
OUT = ROOT / 'docs/aoffix2/pad'
assert set(os.sched_getaffinity(0)) <= set(range(112, 128))
SOURCE.mkdir(parents=True, exist_ok=False)
PAD.mkdir(parents=True, exist_ok=False)
OUT.mkdir(parents=True, exist_ok=False)


def run(argv, label):
    with (OUT / (label + '.log')).open('w') as log:
        subprocess.run(['taskset', '-c', '112-127', *map(str, argv)], cwd=SOURCE,
                       stdout=log, stderr=subprocess.STDOUT, check=True)


with (BASE / 'pad-source.tar').open('wb') as archive:
    subprocess.run(['git', '-C', str(ROOT), 'archive', '5146b78ee'], stdout=archive, check=True)
run(['tar', '-xf', BASE / 'pad-source.tar'], 'extract')
# The public manager and all default-path layouts are unchanged. Only its
# optional ChunkChan and the boot-only replay plan need the candidate layout.
shutil.copyfile(ROOT / 'src/persist/aof.h', SOURCE / 'src/persist/aof.h')
run(['make', '-j16', 'BUILD_ROOT=' + str(PAD), 'all'], 'build')


def text_size(binary):
    elf = Elf(binary)
    return elf.sections[elf.names.index('.text')][5]


wanted = text_size(ROOT / 'build/tomokv')
padding = wanted - text_size(PAD / 'tomokv')
assert padding >= 0, 'PRE layout twin exceeds POST .text; do not silently invert the control'
for attempt in range(4):
    (PAD / 'padding.S').write_text(
        '.text\n.globl tomo_aoffix2_pad\n.type tomo_aoffix2_pad,@function\n'
        'tomo_aoffix2_pad:\n.fill %d,1,0x90\n' % padding +
        '.size tomo_aoffix2_pad,.-tomo_aoffix2_pad\n.section .note.GNU-stack,"",@progbits\n')
    run(['g++', '-c', PAD / 'padding.S', '-o', PAD / 'padding.o'], f'padding-{attempt}')
    recipe = ('aoffix2-pad-link:;$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) '
              '$(OBJ) $(SERVER_ONLY_OBJ) $(BUILD_ROOT)/padding.o -o $(BIN) -Wl,--wrap=main '
              '$(JELIBS) $(LDLIBS) -lm')
    run(['make', '--no-print-directory', '-s', 'BUILD_ROOT=' + str(PAD),
         '--eval=' + recipe, 'aoffix2-pad-link'], f'link-{attempt}')
    actual = text_size(PAD / 'tomokv')
    if actual == wanted:
        break
    padding += wanted - actual
    assert padding >= 0
assert actual == wanted
types = ['AofReplayPlan', 'AofManager::ChunkChan']
layout = {}
for arm, binary in [('POST', ROOT / 'build/tomokv'), ('PAD', PAD / 'tomokv')]:
    program = 'import gdb,json; out={}; exec(' + repr(
        '\n'.join(['for ns in ("tomo","tomo_db0"):', ' for name in ' + repr(types) + ':',
                   '  t=gdb.lookup_type(ns+"::"+name)',
                   '  out[ns+"::"+name] = {"size":int(t.sizeof),"fields":{f.name:int(f.bitpos) for f in t.fields() if f.name and hasattr(f,"bitpos")}}'])) + '); print(json.dumps(out))'
    layout[arm] = json.loads(subprocess.check_output(
        ['gdb', '-nx', '-batch', str(binary), '-ex', 'python ' + program], text=True))
assert layout['POST'] == layout['PAD']
report = dict(kind='A: behaviour twin', behavior='PRE 5146b78ee',
              layout='POST AOF-only ChunkChan and replay plan, plus total .text size',
              limitation='Function addresses may differ; no claim of identical function placement',
              padding_bytes=padding, text_bytes=wanted, layouts=layout,
              sha256=hashlib.sha256((PAD / 'tomokv').read_bytes()).hexdigest())
(OUT / 'kind.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
