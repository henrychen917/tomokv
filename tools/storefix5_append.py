#!/usr/bin/env python3
"""Link the same copy witness against either arm's ordinary production objects."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import wave13_counts as census

p = argparse.ArgumentParser()
p.add_argument('arm'); p.add_argument('--source', type=Path, required=True)
p.add_argument('--objects', type=Path, required=True)
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
census.BUILD = census.ROOT / 'build/storefix5/append'
census.DOC = census.ROOT / 'docs/storefix5/append'
source, objects = a.source.resolve(), a.objects.resolve()
dest = census.BUILD / a.arm
dest.mkdir(parents=True, exist_ok=True)
recipe = subprocess.check_output(['make', '-C', str(source), 'BUILD_ROOT='+str(objects),
                                 '-n', '-W', str(objects/'src/main.o'), 'all'], text=True)
link = shlex.split(next(l for l in recipe.splitlines() if ' -o '+str(objects/'tomokv')+' ' in l))
link = [x for x in link if x != str(objects/'db0/src/main.o')]
link[link.index('-o')+1] = str(dest/'probe')
compile = ['g++', '-std=c++20', '-O2', '-g', '-gz=zlib', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
           '-I'+str(source), '-c', str(census.ROOT/'tests/storefix5_append.cc'), '-o', str(dest/'probe.o')]
link += [str(dest/'probe.o'), '-Wl,--wrap=malloc,--wrap=memcpy', '-Wl,--compress-debug-sections=zlib']
with (dest/'build.log').open('w') as log:
    for cmd in (compile, link):
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
census.save(census.DOC/(a.arm+'-build.json'), dict(compile=compile, link=link,
    binary_sha256=census.sha(dest/'probe'), server_sha256=census.sha(objects/'tomokv')))
result = subprocess.run([str(dest/'probe')], capture_output=True, text=True)
census.save(census.DOC/(a.arm+'-result.json'), dict(exit=result.returncode, stdout=result.stdout,
                                               stderr=result.stderr))
print(result.stdout + result.stderr, end='')
raise SystemExit(result.returncode)
