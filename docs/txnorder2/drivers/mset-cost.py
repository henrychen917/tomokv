#!/usr/bin/env python3
"""Compile and trace a blind-MSET cold-call removal without changing production."""
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
out = root / 'docs/txnorder2/mset-cost-trial'
build = root / 'build/txnorder2/mset-cost-trial'
source = build / 'source'
out.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / 'src', source / 'src', dirs_exist_ok=True)
path = source / 'src/cmd/scatter_engine.inc'
before = path.read_text()
after = before.replace('((!txn_group_prepare(*state, server, owner_io, &pool)) ||',
    '(((state->atomic_apply || state->kind == Kind::Msetnx) &&\n'
    '          !txn_group_prepare(*state, server, owner_io, &pool)) ||')
after = after.replace('        txn_group_barrier_witness(*state, client);',
    '        if (state->kind == Kind::Msetnx) txn_group_barrier_witness(*state, client);')
assert after != before
path.write_text(after)
recipe = subprocess.check_output(['taskset','-c','64-95','make','-n','-W',
    'src/cmd/xshard.cc','all'], text=True).replace('\\\n',' ')
commands = {}
for line in recipe.splitlines():
    if line.startswith('g++ '):
        cmd = shlex.split(line)
        if '-c' in cmd: commands[cmd[cmd.index('-o')+1]] = cmd

def compile_one(ns):
    target = 'build/' + ('db0/' if ns == 'db0' else '') + 'src/cmd/xshard.o'
    cmd = commands[target].copy()
    cmd[cmd.index('src/cmd/xshard.cc')] = str(source/'src/cmd/xshard.cc')
    cmd[cmd.index('-o')+1] = str(build/(ns+'.o'))
    cmd += ['-g0']
    cmd = ['taskset','-c','64-95',*cmd]
    with (out/(ns+'-compile.log')).open('w') as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    assert rc == 0
    return dict(namespace=ns,command=cmd,exit_code=rc)

with concurrent.futures.ThreadPoolExecutor(2) as pool:
    compiled = list(pool.map(compile_one, ['normal','db0']))
(out/'compile.json').write_text(json.dumps(compiled,indent=2)+'\n')
for ns in ['normal','db0']:
    receipt = json.loads((root/'docs/txnorder2/paths-final/atomic'/('post-'+ns+'-build.json')).read_text())
    folder = build/'atomic'/('post-'+ns)
    folder.mkdir(parents=True,exist_ok=True)
    cmd = receipt['link']
    for i,arg in enumerate(cmd):
        if arg == str(root/'build/src/cmd/xshard.o'):cmd[i] = str(build/'normal.o')
        if arg == str(root/'build/db0/src/cmd/xshard.o'):cmd[i] = str(build/'db0.o')
    cmd[cmd.index('-o')+1] = str(folder/'probe')
    with (out/(ns+'-link.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,check=True)
spec=importlib.util.spec_from_file_location('paths',Path(__file__).with_name('paths.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
p.OUT=out;p.BUILD=build
(out/'atomic').mkdir(exist_ok=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    rows=list(pool.map(p.trace,[('atomic','post',n,m,'MSET') for n in ['normal','db0'] for m in ['1s','2s']]))
(out/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
assert all(r['exit_code']==0 for r in rows)
