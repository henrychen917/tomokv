#!/usr/bin/env python3
"""Link a scheduling twin from the current production objects; never boot here."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import subprocess
import source_tokens as cpp

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def undefined_symbol(obj, role):
    suffix = {'function_snapshot_save': '22function_snapshot_save',
              'append_function_journal': '10AofManager23append_function_journal'}[role]
    matches = [line.split()[-1] for line in subprocess.check_output(
        ['nm', str(obj)], text=True).splitlines()
        if ' U ' in line and any(cpp.canonical_symbol(line.split()[-1]).startswith(prefix + suffix)
                                 for prefix in ('_ZN4tomo', '_ZN8tomo_db0'))]
    if len(matches) != 1:
        raise ValueError(f'{obj}: expected one undefined {role}, found {len(matches)}')
    return matches[0]

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--objects', type=Path, default=ROOT/'build')
p.add_argument('--symbols-only', action='store_true', help='validate linker anchors without compiling')
a = p.parse_args()
a.output = a.output.resolve(); a.objects = a.objects.resolve()
a.output.mkdir(parents=True, exist_ok=True)
if a.symbols_only:
    for ns in ('normal', 'db0'):
        prefix = a.objects / ('db0' if ns == 'db0' else '.')
        print(ns, undefined_symbol(prefix/'src/snapshot/snapshot.o', 'function_snapshot_save'),
              undefined_symbol(prefix/'src/cmd/functions.o', 'append_function_journal'))
    raise SystemExit(0)
recipe = subprocess.check_output(['make', '-n', 'BUILD_ROOT='+str(a.objects),
    '-W', str(a.objects/'src/main.o'), 'all'], text=True)
link = shlex.split(next(line for line in recipe.splitlines()
    if ' -o '+str(a.objects/'tomokv')+' ' in line))
commands = []
for ns in ('normal', 'db0'):
    obj = a.output/(ns+'.o')
    symbol = undefined_symbol(a.objects/('db0/' if ns=='db0' else '')/'src/snapshot/snapshot.o',
                              'function_snapshot_save')
    journal = undefined_symbol(a.objects/('db0/' if ns=='db0' else '')/'src/cmd/functions.o',
                               'append_function_journal')
    command = ['g++', '-std=c++20', '-O2', '-g', '-gz=zlib', '-march=native',
               '-pthread', '-DTOMO_JEMALLOC', '-I.', '-c',
               str(ROOT/'tests/wave14_capture_hook.cc'), '-o', str(obj)]
    command += ['-DTOMO_WAVE14_SAVE_SYMBOL=' + json.dumps(symbol),
                '-DTOMO_WAVE14_JOURNAL_SYMBOL=' + json.dumps(journal)]
    if ns == 'db0': command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    subprocess.run(command, check=True); commands.append(command)
    link += [str(obj), '-Wl,--wrap='+symbol]
    link += ['-Wl,--wrap='+journal]
link[link.index('-o')+1] = str(a.output/'tomokv')
subprocess.run(link, check=True)
save(a.output/'binding.json', dict(commands=commands, link=link,
    server_sha256=sha(a.objects/'tomokv'), scheduled_sha256=sha(a.output/'tomokv'),
    hook_sha256=sha(ROOT/'tests/wave14_capture_hook.cc')))
