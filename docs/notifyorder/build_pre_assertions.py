#!/usr/bin/env python3
"""Build the current notify-oom assertions against PRE implementation and objects."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/notifyorder'
OUT = BASE / 'pre-new-assertions'
OUT.mkdir(exist_ok=True)
source = ROOT / 'tests/netcmd_unit.cc'
obj = OUT / 'netcmd_unit.o'
binary = OUT / 'netcmd-unit'
compile = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
           '-DTOMO_JEMALLOC', '-Wno-mismatched-new-delete', '-I'+str(BASE), '-I'+str(ROOT),
           '-MMD', '-MF', str(OUT / 'netcmd_unit.d'), '-c', str(source), '-o', str(obj)]
commands = [shlex.split(line) for line in (ROOT / 'docs/notifyorder/build-pre-netcmd.log').read_text().splitlines()
            if line.startswith('g++ ') and ' -o build/netcmd-unit ' in line]
assert len(commands) == 1
link = commands[0]
objects = []
for i, value in enumerate(link):
    if value == 'build/tests/netcmd_unit.o':
        link[i] = str(obj)
    elif value.endswith('.o'):
        path = (BASE / value).resolve()
        assert path.is_file() and path.is_relative_to(BASE), path
        objects.append(dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        link[i] = str(path)
link[link.index('-o')+1] = str(binary)
dependencies = [source, ROOT / 'tests/netcmd_unit.h', ROOT / 'tests/notify_order_checks.inc']
makefile = OUT / 'Makefile'
makefile.write_text(f'all: {binary}\n{binary}: {obj}\n\t{shlex.join(link)}\n'
                    f'{obj}: '+ ' '.join(map(str, dependencies)) + '\n\t'+shlex.join(compile)+'\n')
subprocess.run(['taskset', '-c', '96-111', 'make', '-j16', '-f', str(makefile)], cwd=ROOT, check=True)
deps = (OUT / 'netcmd_unit.d').read_text()
dependency_paths = [Path(value).resolve() for value in shlex.split(deps.replace('\\\n', ' '))[1:]]
assert not any(p.is_relative_to(ROOT / 'src') for p in dependency_paths), \
    'current production header/source leaked into PRE unit'
assert (BASE / 'src/cmd/xshard.cc').resolve() in dependency_paths, \
    'PRE command implementation was not included'
production_dependencies = sorted({p for p in dependency_paths if p.is_relative_to((BASE / 'src').resolve())})
receipt = dict(base='8656f9fa924fc06aa128504fca8aa99436aa9e41',
               purpose='Current assertions, original PRE production implementation; no candidate feature code',
               source_assertions={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies},
               compile=compile, link=link, objects=objects, output=str(binary.relative_to(ROOT)),
               sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
               production_dependencies=[dict(path=str(p.relative_to(ROOT)),
                                             sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                                        for p in production_dependencies])
(ROOT / 'docs/notifyorder/pre-new-assertions.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('compile','link','objects','production_dependencies')}, indent=2))
print(f'{len(production_dependencies)} canonical PRE source/header dependencies verified')
