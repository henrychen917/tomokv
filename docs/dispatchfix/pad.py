#!/usr/bin/env python3
"""Build PAD-A: PRE behavior, POST cold data layouts and aggregate .text size.

Internal function placement is not matched. This controls the changed data
layouts and text growth; it does not establish arbitrary code-placement effects.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf
BASE = ROOT / 'build/dispatchfix-pad'
SOURCE, OBJECTS = BASE / 'source', BASE / 'objects'
OUT = ROOT / 'docs/dispatchfix/pad'
assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
fresh_source = not SOURCE.exists()
SOURCE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
revision = 'a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e'
archive = subprocess.check_output(['git', 'archive', revision, 'src', 'third_party', 'Makefile'], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    if fresh_source:
        tar.extractall(SOURCE, filter='data')
# Cold images/plans keep candidate layouts. Their new fields remain unused by
# PRE code. No dispatch/routing/permission implementation is copied from POST.
headers = ['src/cmd/acl.h', 'src/persist/aof.h', 'src/snapshot/snapshot.h']
for header in headers:
    if (ROOT / header).read_bytes() != (SOURCE / header).read_bytes():
        shutil.copyfile(ROOT / header, SOURCE / header)

def run(argv, label):
    with (OUT / (label + '.log')).open('w') as log:
        subprocess.run(list(map(str, argv)), cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT, check=True)

def text_size(binary):
    elf = Elf(binary)
    return elf.sections[elf.names.index('.text')][5]

run(['make', '-j16', 'BUILD_ROOT=' + str(OBJECTS), 'all'], 'build')
post = ROOT / 'build/tomokv'
wanted = text_size(post)
padding = wanted - text_size(OBJECTS / 'tomokv')
assert padding >= 0, 'PRE layout twin exceeds POST: cannot silently invert the control'
output = ROOT / 'build/tomokv-PAD-A'
for attempt in range(4):
    (BASE / 'padding.cc').write_text('asm(R"(.pushsection .text.dispatchfix_pad,"ax",@progbits\n.fill '
        + str(padding) + ',1,0x90\n.popsection\n)");\n')
    # Same compiler flags retain GNU ISA/CET properties when adding the object.
    run(['g++', '-std=c++20', '-O2', '-g', '-march=native', '-c', BASE / 'padding.cc',
         '-o', BASE / 'padding.o'], 'padding-' + str(attempt))
    recipe = ('dispatchfix-pad-link:;$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) '
              '$(OBJ) $(SERVER_ONLY_OBJ) ' + str(BASE / 'padding.o') + ' -o ' + str(output) +
              ' -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm')
    run(['make', '--no-print-directory', '-s', 'BUILD_ROOT=' + str(OBJECTS),
         '--eval=' + recipe, 'dispatchfix-pad-link'], 'link-' + str(attempt))
    actual = text_size(output)
    if actual == wanted:
        break
    padding += wanted - actual
    assert padding >= 0
assert actual == wanted
layout = {}
for arm, binary in [('POST', post), ('PAD-A', output)]:
    program = 'import gdb,json; out={}; exec(' + repr(
        '\n'.join(['for ns in ("tomo", "tomo_db0"):',
                   ' for name in ("AclSelector", "AclPerm", "SnapshotLoadPlan", "AofReplayPlan", "AofManager"):',
                   '  t=gdb.lookup_type(ns+"::"+name)',
                   '  out[ns+"::"+name] = {"size":int(t.sizeof),"fields":{f.name:int(f.bitpos) for f in t.fields() if f.name and hasattr(f,"bitpos")}}'])) + '); print(json.dumps(out))'
    raw = subprocess.check_output(['gdb', '-nx', '-batch', str(binary), '-ex', 'python ' + program], text=True)
    layout[arm] = json.loads(raw)
assert layout['POST'] == layout['PAD-A']
report = dict(kind='A: behaviour twin', behavior='PRE ' + revision, copied_headers=headers,
              layout='POST cold ACL/persistence images and aggregate .text size',
              limitation='Function placement is not matched; code placement remains a merit-review limit.',
              padding_bytes=padding, text_bytes=wanted, layouts=layout,
              arms={name:dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             text_bytes=text_size(path))
                    for name,path in [('PRE', ROOT/'build/tomokv-PRE'), ('POST', post), ('PAD-A', output)]})
(OUT / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
