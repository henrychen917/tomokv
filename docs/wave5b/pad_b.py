#!/usr/bin/env python3
"""B: inverse control, fallback behavior with padding restoring wave-5 text size."""
from collections import Counter
import hashlib,json,os,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
assert os.sched_getaffinity(0)<=set(range(64,112))
before=Elf(ROOT/'build/tomokv');baseline=Elf(ROOT/'build/tomokv-wave5b-BASE')
def text(e):return e.sections[e.names.index('.text')]
gap=text(baseline)[5]-text(before)[5];assert gap>5
out=ROOT/'build/wave5b/pad-b';out.mkdir(parents=True,exist_ok=True)
note=before.sections[before.names.index('.note.gnu.property')]
properties=before.data[note[4]:note[4]+note[5]]
(out/'pad.S').write_text('.section .text.wave5b_pad_b,"ax",@progbits\n.balign 1\n'
    '.globl wave5b_pad_b\n.hidden wave5b_pad_b\n.type wave5b_pad_b,@function\nwave5b_pad_b:\nendbr64\nret\n'
    f'.fill {gap-5},1,0x90\n.size wave5b_pad_b,.-wave5b_pad_b\n.section .note.GNU-stack,"",@progbits\n'
    '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte '+','.join(hex(x) for x in properties)+'\n')
subprocess.run(['g++','-c',str(out/'pad.S'),'-o',str(out/'pad.o')],check=True)
cmd=shlex.split(next(x for x in reversed((ROOT/'build/wave5b/fallback-build.log').read_text().splitlines()) if x.startswith('g++ ') and ' -Wl,--wrap=main ' in x))
binary=ROOT/'build/tomokv-wave5b-PAD-B'
cmd[cmd.index('-o')+1]=str(binary);cmd.insert(cmd.index('-o'),str(out/'pad.o'));cmd.append('-Wl,--strip-debug')
subprocess.run(cmd,cwd=ROOT,check=True)
twin=Elf(binary);assert text(twin)[5]==text(baseline)[5]
def symbols(e):return Counter((s['name'],s['value'],s['size']) for s in e.symbols if s['info']&15==2 and s['sec']==e.names.index('.text'))
assert not symbols(before)-symbols(twin) and len(symbols(twin)-symbols(before))==1
sha=lambda data:hashlib.sha256(data).hexdigest()
r=dict(kind='B: inverse control',behavior='fallback; WB4.1 reverted',baseline_sha256=sha(baseline.data),
       candidate_sha256=sha(before.data),pad_sha256=sha(twin.data),candidate_text=text(before)[5],
       baseline_text=text(baseline)[5],pad_text=text(twin)[5],padding_bytes=gap,
       original_candidate_function_addresses_sizes_preserved=True,link=cmd)
(ROOT/'docs/wave5b/pad-b.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
