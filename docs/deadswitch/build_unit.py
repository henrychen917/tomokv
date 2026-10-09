#!/usr/bin/env python3
"""Link a serverless witness to a selected production object arm; never runs it."""
import argparse
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('arm', type=Path)
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--db0', action='store_true')
a = p.parse_args()
objects = [o for o in sorted((a.arm / 'src').rglob('*.o')) if o != a.arm / 'src/main.o']
defines = []
if a.db0:
    objects += [o for o in sorted((a.arm / 'db0/src').rglob('*.o'))
                if o != a.arm / 'db0/src/main.o']
    defines = ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
assert objects and all(o.exists() for o in objects)
command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
           '-DTOMO_JEMALLOC', *defines, '-I.', str(a.source), *map(str, objects),
           '-o', str(a.output), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm']
subprocess.run(command, check=True)
