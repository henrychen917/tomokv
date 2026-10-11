#!/usr/bin/env python3
"""Build an isolated MSETNX barrier-removed control; never starts a server."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
output = root / 'build/txnfix3/barrier-off'
source = output / 'source'
source.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / 'src', source / 'src', dirs_exist_ok=True)
path = source / 'src/cmd/txn_group.inc'
old = path.read_text()
needle = '        state.barrier = true;'
assert old.count(needle) == 1
replacement = '        if (state.kind != Kind::Msetnx) state.barrier = true;'
path.write_text(old.replace(needle, replacement))
recipe = subprocess.check_output(['make', '-n', '-W', 'src/cmd/xshard.cc', 'all'], cwd=root, text=True).replace('\\\n', ' ')
commands = {}
for line in recipe.splitlines():
    if line.startswith('g++ '):
        cmd = shlex.split(line)
        if '-o' in cmd:
            commands[cmd[cmd.index('-o') + 1]] = cmd


def compile_one(prefix):
    target = 'build/' + prefix + 'src/cmd/xshard.o'
    command = commands[target].copy()
    obj = output / (('db0-' if prefix else '') + 'xshard.o')
    command[command.index('src/cmd/xshard.cc')] = str(source / 'src/cmd/xshard.cc')
    command[command.index('-o') + 1] = str(obj)
    command += ['-g0']
    command = ['taskset', '-c', '112-127', *command]
    with (output / (obj.name + '.log')).open('w') as log:
        subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    return dict(replaces=target, object=str(obj), command=command)


with concurrent.futures.ThreadPoolExecutor(2) as pool:
    objects = list(pool.map(compile_one, ('', 'db0/')))
command = commands['build/tomokv'].copy()
for row in objects:
    command[command.index(row['replaces'])] = row['object']
binary = output / 'tomokv'
command[command.index('-o') + 1] = str(binary)
command = ['taskset', '-c', '112-127', *command]
with (output / 'link.log').open('w') as log:
    subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
receipt = root / 'docs/txnfix/txnfix3/barrier-control'
receipt.mkdir(parents=True, exist_ok=True)
(receipt / 'build.json').write_text(json.dumps(dict(
    mutation=dict(file='src/cmd/txn_group.inc', before=needle, after=replacement),
    source_before_sha256=hashlib.sha256(old.encode()).hexdigest(),
    source_after_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    objects=objects, link=command, binary=str(binary),
    sha256=hashlib.sha256(binary.read_bytes()).hexdigest()), indent=2) + '\n')
print(binary, flush=True)
