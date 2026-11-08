#!/usr/bin/env python3
"""Compile-only scatter jump-padding trial, with linked production count scopes."""
import json, os, shlex, shutil, subprocess
import exec1sd as d
assert os.sched_getaffinity(0)<=set(range(64,96))
source=d.OUT/'alignment-source';source.mkdir(exist_ok=True)
shutil.copytree(d.ROOT/'src',source/'src',dirs_exist_ok=True)
p=source/'src/cmd/scatter_engine.inc'
s=p.read_text().replace('optimize("align-jumps=16:8")','optimize("align-jumps=1,align-loops=1")')
p.write_text(s)
command=subprocess.check_output(['make','-n','-W','src/cmd/xshard.cc','build/src/cmd/xshard.o'],text=True)
args=shlex.split(next(l for l in command.splitlines() if ' -c src/cmd/xshard.cc ' in l))
args[args.index('src/cmd/xshard.cc')]=str(source/'src/cmd/xshard.cc')
args[args.index('-o')+1]=str(d.OUT/'alignment-xshard.o');args.insert(args.index('-I.'),'-I'+str(source))
if '--reuse-object' not in __import__('sys').argv:
 d.run(args,d.OUT/'evidence/alignment-build.log')
scope=d.scope_module();scope.ARMS['ALIGN']=(d.ROOT,d.ROOT/'build')
scope.OBJECT_OVERRIDES[str(d.ROOT/'build/src/cmd/xshard.o')]=str(d.OUT/'alignment-xshard.o')
scope.FIXTURE=d.ROOT/'tests/txnorder_command_scope.cc'
scope.build('ALIGN','normal')
import crlffix_fast_scope as fast
fast.scope=scope;fast.OUT=scope.OUT
prepared=fast.prepare('ALIGN','normal')
rows=[fast.run(('ALIGN','normal',command,'2s',batch,atomic,-1),{('ALIGN','normal'):prepared})
      for command,batch,atomic in [('MSET',1,1),('MSET',32,1),('MGET',1,1),('MGET',32,1)]]
d.save(d.DOCS/'alignment-counts.json',rows)
