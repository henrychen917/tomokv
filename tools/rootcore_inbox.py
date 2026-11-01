#!/usr/bin/env python3
"""Build a diagnostic source copy; no hooks or storage enter production."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--revision')
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
source=a.output/'source'
source.mkdir(exist_ok=True)
if a.revision:
    archive=subprocess.Popen(['git','archive',a.revision,'src'],stdout=subprocess.PIPE)
    subprocess.run(['tar','-x','-C',str(source)],stdin=archive.stdout,check=True)
    archive.stdout.close()
    assert archive.wait()==0
else:
    shutil.copytree('src',source/'src',dirs_exist_ok=True)
h=source/'src/core/thread.h'
h.write_text(h.read_text().replace('private:', 'public:'))
binary=a.output/'inbox'
subprocess.run(['g++','-std=c++20','-O2','-g','-march=native','-pthread',
                '-I'+str(source),'-I.','tests/rootcore_inbox.cc','-o',str(binary),
                '-luring'],check=True)
failed=False
for kind in ('client','transfer','task','fused','flush'):
    result=subprocess.run([str(binary),kind],check=False)
    failed|=result.returncode!=0
raise SystemExit(int(failed))
