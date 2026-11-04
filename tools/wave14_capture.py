#!/usr/bin/env python3
"""Link a scheduling twin from the current production objects; never boot here."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
from wave14 import ROOT, sha, save

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--objects', type=Path, default=ROOT/'build')
a = p.parse_args()
a.output = a.output.resolve(); a.objects = a.objects.resolve()
a.output.mkdir(parents=True, exist_ok=True)
recipe = subprocess.check_output(['make', '-n', 'BUILD_ROOT='+str(a.objects),
    '-W', str(a.objects/'src/main.o'), 'all'], text=True)
link = shlex.split(next(line for line in recipe.splitlines()
    if ' -o '+str(a.objects/'tomokv')+' ' in line))
commands = []
for ns in ('normal', 'db0'):
    obj = a.output/(ns+'.o')
    command = ['g++', '-std=c++20', '-O2', '-g', '-gz=zlib', '-march=native',
               '-pthread', '-DTOMO_JEMALLOC', '-I.', '-c',
               str(ROOT/'tests/wave14_capture_hook.cc'), '-o', str(obj)]
    if ns == 'db0': command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    subprocess.run(command, check=True); commands.append(command)
    symbol = next(line.split()[-1] for line in subprocess.check_output(
        ['nm', str(a.objects/('db0/' if ns=='db0' else '')/'src/snapshot/snapshot.o')],
        text=True).splitlines() if ' U ' in line and 'function_snapshot_save' in line)
    link += [str(obj), '-Wl,--wrap='+symbol]
    journal = next(line.split()[-1] for line in subprocess.check_output(
        ['nm', str(a.objects/('db0/' if ns=='db0' else '')/'src/cmd/functions.o')],
        text=True).splitlines() if ' U ' in line and 'append_function_journal' in line)
    link += ['-Wl,--wrap='+journal]
link[link.index('-o')+1] = str(a.output/'tomokv')
subprocess.run(link, check=True)
save(a.output/'binding.json', dict(commands=commands, link=link,
    server_sha256=sha(a.objects/'tomokv'), scheduled_sha256=sha(a.output/'tomokv'),
    hook_sha256=sha(ROOT/'tests/wave14_capture_hook.cc')))
