#!/usr/bin/env python3
"""Regenerate comments, rebuild, and prove that runtime sections did not change."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 80)))
sys.path.insert(0, str(ROOT / 'tools'))
from assert_map import lex
from lbstall_artifacts import Elf


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


sources = [ROOT / 'src/core' / name for name in ('reorder.cc', 'io_loop.h', 'ex_loop.h')]
before = {str(path.relative_to(ROOT)): path.read_text() for path in sources}
old_binary = ROOT / 'build/tomokv-wave8b-before-comment-sync'
assert not old_binary.exists(), 'retain the previous attempt'
shutil.copy2(ROOT / 'build/tomokv', old_binary)
subprocess.run(['python3', 'tests/r7shadow_sync.py', '--write'], check=True)
changed = []
for path in sources:
    name = str(path.relative_to(ROOT))
    old, new = before[name], path.read_text()
    assert [(t.kind, t.text) for t in lex(old)] == [(t.kind, t.text) for t in lex(new)], name
    if old != new:
        changed.append(dict(path=name, before_sha256=hashlib.sha256(old.encode()).hexdigest(),
                            after_sha256=sha(path), identical_cpp_tokens=True))
assert [row['path'] for row in changed] == ['src/core/reorder.cc']
with (ROOT / 'build/wave8b/comment-sync-build.log').open('w') as log:
    subprocess.run(['make', '-j16', 'all'], stdout=log, stderr=subprocess.STDOUT, check=True)


def runtime(path):
    elf = Elf(path)
    sections = {}
    for index, (name, section) in enumerate(zip(elf.names, elf.sections)):
        if not section[2] & 2 or name == '.note.gnu.build-id':
            continue
        sections[name] = dict(type=section[1], flags=section[2], address=section[3],
                              offset=section[4], size=section[5], alignment=section[8],
                              sha256=None if section[1] == 8 else
                              hashlib.sha256(elf.section_data(index)).hexdigest())
    entry, phoff = struct.unpack_from('<QQ', elf.data, 24)
    width, count = struct.unpack_from('<HH', elf.data, 54)
    programs = [list(struct.unpack_from('<IIQQQQQQ', elf.data, phoff + i * width))
                for i in range(count)]
    symbols = sorted((s['name'], s['value'], s['size'], s['info']) for s in elf.symbols)
    return dict(entry=entry, programs=programs, sections=sections, symbols=symbols)


a, b = runtime(old_binary), runtime(ROOT / 'build/tomokv')
assert a == b, 'comment regeneration changed runtime bytes, layout, or symbols'
receipt = dict(before=dict(path=str(old_binary), sha256=sha(old_binary)),
               after=dict(path=str(ROOT / 'build/tomokv'), sha256=sha(ROOT / 'build/tomokv')),
               changed_sources=changed, identical=True,
               checked='Every allocated section except GNU build-id, all program headers, entry point, and symbol names/addresses/sizes; C++ tokens identical.',
               exclusion='GNU build-id and nonallocated debug/linker metadata may change after comment regeneration.',
               sections=a['sections'], symbol_count=len(a['symbols']))
(ROOT / 'docs/wave8b/comment-sync.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Comment sync: runtime bytes, layout and symbols identical', flush=True)
subprocess.run(['python3', 'docs/wave8b/production_build.py'], check=True)
