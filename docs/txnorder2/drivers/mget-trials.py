#!/usr/bin/env python3
"""Compile-only isolation trials for the DB0 MGET argument spill, then trace it.

All variants live in build/. None changes the production tree or measures rate.
"""
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/txnorder2/mget-trials';OUT.mkdir(exist_ok=True)
BUILD=ROOT/'build/txnorder2/mget-trials';BUILD.mkdir(exist_ok=True)
recipe=subprocess.check_output(['make','-n','-W','src/cmd/xshard.cc','all'],text=True).replace('\\\n',' ')
base=next(shlex.split(line) for line in recipe.splitlines()
          if line.startswith('g++ ') and '-o build/db0/src/cmd/xshard.o' in line)
plans=['cold','volatile','budget-minus','budget-plus']
def compile_one(name):
    directory=BUILD/name;directory.mkdir(exist_ok=True)
    shutil.copytree(ROOT/'src',directory/'src',dirs_exist_ok=True)
    path=directory/'src/cmd/scatter_engine.inc';source=path.read_text()
    if name=='cold':
        source=source.replace('#if TOMO_SINGLE_DATABASE\n[[gnu::noinline]]\n#else\n[[gnu::cold, gnu::noinline]]\n#endif',
                              '[[gnu::cold, gnu::noinline]]',1)
    if name=='volatile':source=source.replace('const uint32_t execution_owner = owner_thread_id;',
                                              'const volatile uint32_t execution_owner = owner_thread_id;',1)
    path.write_text(source)
    command=base.copy()
    command[command.index('src/cmd/xshard.cc')]=str(directory/'src/cmd/xshard.cc')
    command[command.index('-o')+1]=str(directory/'xshard.o')
    budget=141091 if name=='budget-minus' else 141219 if name=='budget-plus' else 141155
    command=[f'large-unit-insns={budget}' if x.startswith('large-unit-insns=') else x for x in command]
    command=['taskset','-c','72-79',*command,'-g0']
    with (OUT/(name+'-build.log')).open('w') as f:rc=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT).returncode
    row=dict(name=name,command=command,returncode=rc)
    (OUT/(name+'-build.json')).write_text(json.dumps(row,indent=2)+'\n')
    assert rc==0
    return row
with concurrent.futures.ThreadPoolExecutor(4) as pool:compiled=list(pool.map(compile_one,plans))
spec=importlib.util.spec_from_file_location('paths',Path(__file__).with_name('paths.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
rows=[]
for name in plans:
    directory=BUILD/name;p.BUILD=directory;p.OUT=OUT/name;p.OUT.mkdir(exist_ok=True)
    (p.OUT/'mget').mkdir(exist_ok=True)
    folder=directory/'mget/post-db0';folder.mkdir(parents=True,exist_ok=True)
    receipt=json.loads((ROOT/'docs/txnorder2/paths-final2b/mget/post-db0-build.json').read_text())
    link=receipt['link']
    link=[str(directory/'xshard.o') if x==str(ROOT/'build/db0/src/cmd/xshard.o') else x for x in link]
    link[link.index('-o')+1]=str(folder/'probe')
    with (OUT/(name+'-link.log')).open('w') as f:subprocess.run(link,stdout=f,stderr=subprocess.STDOUT,check=True)
    row=p.trace(('mget','post','db0','2s','missing'))
    row['variant']=name;rows.append(row)
(OUT/'results.json').write_text(json.dumps(dict(compiles=compiled,runs=rows),indent=2)+'\n')
