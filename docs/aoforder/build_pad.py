#!/usr/bin/env python3
"""Frozen PAD-A builder: PRE behavior, final aoforder ordinary-hot text placement.

This relinks the unmodified PRE objects with unreachable NOP sections. It does
not patch instructions or introduce a runtime selector. The hard-coded gaps are
specific to the recorded GCC/Makefile build, and the address/size checks reject a
mismatched candidate. All selected linked hot function addresses must match POST.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf, HOT

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('pre',type=Path)
p.add_argument('post',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
a.pre=a.pre.resolve(); a.post=a.post.resolve(); a.output=a.output.resolve()
assert a.output.is_relative_to(ROOT/'build')
a.output.mkdir(parents=True,exist_ok=True)
prefix=['taskset','-c',','.join(map(str,sorted(os.sched_getaffinity(0))))]
commands=[]; objects={}
for ns,hot,cold in [('db0',12944,176),('tomo',12496,92)]:
    source=a.output/(ns+'.S'); obj=a.output/(ns+'.o')
    source.write_text(f'.section .text.unlikely.aoforder_pad_{ns},"ax",@progbits\n'
        f'.type aoforder_cold_pad_{ns},@function\naoforder_cold_pad_{ns}:\n'
        f'.fill {cold},1,0x90\n.size aoforder_cold_pad_{ns},.-aoforder_cold_pad_{ns}\n'
        f'.text\n.type aoforder_text_pad_{ns},@function\naoforder_text_pad_{ns}:\n'
        f'.fill {hot},1,0x90\n.size aoforder_text_pad_{ns},.-aoforder_text_pad_{ns}\n'
        '.section .note.GNU-stack,"",@progbits\n')
    cmd=prefix+['g++','-c',str(source),'-o',str(obj)]
    subprocess.run(cmd,check=True);commands.append(cmd);objects[ns]=str(obj)
dry=subprocess.check_output(prefix+['make','-n','-B','BUILD_ROOT='+str(a.pre),'all'],cwd=ROOT,text=True)
link=next(shlex.split(line) for line in dry.splitlines() if line.startswith('g++ ') and ' -c ' not in line)
argv=[]
for item in link:
    argv.append(item)
    if item.endswith('/src/persist/aof.o'):
        argv.append(objects['db0' if '/db0/' in item else 'tomo'])
argv[argv.index('-o')+1]=str(a.output/'tomokv')
post=Elf(a.post/'tomokv'); section=post.sections[post.names.index('.text')]
argv+=['-Wl,-Map='+str(a.output/'link.map'),'-Wl,--section-start=.text='+hex(section[3])]
with (a.output/'link.log').open('w') as out:
    subprocess.run(prefix+argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
commands.append(prefix+argv)
pre,pad=Elf(a.pre/'tomokv'),Elf(a.output/'tomokv')
old,new,twin=pre.functions(),post.functions(),pad.functions()
names=sorted(old.keys() & new.keys())
labels=subprocess.check_output(prefix+['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines()
rows=[dict(symbol=s,name=n,pre=old[s]['value'],post=new[s]['value'],pad=twin[s]['value'],
           equal=twin[s]['value']==new[s]['value']) for s,n in zip(names,labels) if HOT.search(n)]
text=pad.sections[pad.names.index('.text')]
report=dict(kind='A: PRE behavior with POST text size and ordinary-hot function placement',
    pre=str(a.pre/'tomokv'),post=str(a.post/'tomokv'),pad=str(a.output/'tomokv'),
    sha256={k:hashlib.sha256(f.read_bytes()).hexdigest() for k,f in
            [('pre',a.pre/'tomokv'),('post',a.post/'tomokv'),('pad',a.output/'tomokv')]},
    hot_count=len(rows),hot_layout_equal=sum(r['equal'] for r in rows),
    text_address_equal=text[3]==section[3],text_size_equal=text[5]==section[5],
    post_text=section[5],pad_text=text[5],rows=rows,commands=commands)
(a.output/'layout.json').write_text(json.dumps(report,indent=2)+'\n')
assert len(rows)==544 and all(r['equal'] for r in rows), 'ordinary-hot placement differs'
assert report['text_address_equal'] and report['text_size_equal'], 'text range differs'
print(json.dumps({k:v for k,v in report.items() if k not in ('rows','commands')},indent=2))
