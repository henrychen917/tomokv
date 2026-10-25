#!/usr/bin/env python3
"""Link a PRE-behaviour, POST-total-text-size control; never execute it here."""
from pathlib import Path
import hashlib,json,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
BUILD=ROOT/'build/datafix2';BUILD.mkdir(exist_ok=True)
def textsize(path):
    e=Elf(path);return e.sections[e.names.index('.text')][5]
pre=ROOT/'build/tomokv-pre';post=ROOT/'build/tomokv';pad=ROOT/'build/tomokv-pad-a'
plan=subprocess.check_output(['make','-B','-n','all'],cwd=ROOT,text=True)
line=next(x for x in plan.splitlines() if ' -o build/tomokv ' in x)
args=shlex.split(line)
args=[str(ROOT/'build/pre-objects'/x) if x.startswith('build/') and x.endswith('.o') else x for x in args]
args[args.index('-o')+1]=str(pad)
asm=BUILD/'pad-a.S';obj=BUILD/'pad-a.o';args.insert(args.index('-o'),str(obj))
want=textsize(post);count=max(0,want-textsize(pre))
for attempt in range(3):
    asm.write_text('.section .text.datafix2_pad,"ax",@progbits\n.balign 1\n.fill '+str(count)+',1,0x90\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['g++','-c',str(asm),'-o',str(obj)],check=True,cwd=ROOT)
    subprocess.run(args,check=True,cwd=ROOT)
    actual=textsize(pad)
    if actual==want:break
    count+=want-actual
    assert count>=0, 'POST shrank: PRE must be rebuilt with a documented size-control budget'
else:raise AssertionError((actual,want))
report=dict(kind='A (behaviour twin)',definition='PRE behavior and unchanged locked object layouts, with unreachable trailing NOPs matching POST total .text size.',pre_text=textsize(pre),post_text=want,pad_text=actual,padding_bytes=count,link_command=args,limit='Total text size only; this does not match each POST function address or instruction-cache alignment.',sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in [('PRE',pre),('POST',post),('PAD_A',pad)]})
(ROOT/'docs/datafix2/pad-a.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='link_command'},indent=2))
