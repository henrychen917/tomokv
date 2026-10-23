#!/usr/bin/env python3
"""A: wave-5 POST behavior at the fallback's smaller .text size.

The revert shrinks text, so appending NOPs to the original binary cannot form A.
Compile identical wave-5 source with function alignment disabled, then append
unreachable padding to the candidate's exact text size. This controls total
text size, not function placement; no policy or runtime selection is added.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from lbstall_artifacts import Elf

assert os.sched_getaffinity(0) <= set(range(64,112))
source = ROOT/'build/wave5b/base-source'
out = ROOT/'build/wave5b/pad-a'
out.mkdir(parents=True, exist_ok=True)
candidate = ROOT/'build/tomokv'
baseline = ROOT/'build/tomokv-wave5b-BASE'
binary = ROOT/'build/tomokv-wave5b-PAD-A'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def text(elf): return elf.sections[elf.names.index('.text')]
flags = '-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -falign-functions=1'
build = ['make','-j32','BUILD_ROOT=build-align','CXXFLAGS='+flags,'all']
log = out/'build.log'
with log.open('w') as f: subprocess.run(build,cwd=source,stdout=f,stderr=subprocess.STDOUT,check=True)
aligned = source/'build-align/tomokv'
before = Elf(aligned)
target = text(Elf(candidate))[5]
gap = target-text(before)[5]
assert gap >= 5, ('alignment must leave room for the behavior-preserving size control', gap)
links = [line for line in log.read_text().splitlines()
         if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line]
if links:
    command = shlex.split(links[-1])
else:
    # An unchanged rebuild is fresh; preserve the captured link rather than
    # forcing every object to rebuild just to print the same command again.
    command = json.loads((ROOT/'docs/wave5b/pad-a.json').read_text())['link']
    command.remove(str(out/'pad.o'))
command[command.index('-o')+1] = str(binary)
obj = out/'pad.o'
command.insert(command.index('-o'),str(obj))
note = before.sections[before.names.index('.note.gnu.property')]
properties = before.data[note[4]:note[4]+note[5]]
for attempt in range(3):
    asm = ('.section .text.wave5b_pad_a,"ax",@progbits\n.balign 1\n'
           '.globl wave5b_pad_a\n.hidden wave5b_pad_a\n.type wave5b_pad_a,@function\n'
           'wave5b_pad_a:\nendbr64\nret\n'+f'.fill {gap-5},1,0x90\n'
           '.size wave5b_pad_a,.-wave5b_pad_a\n.section .note.GNU-stack,"",@progbits\n'
           '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte '+
           ','.join(hex(x) for x in properties)+'\n')
    (out/'pad.S').write_text(asm)
    subprocess.run(['g++','-c',str(out/'pad.S'),'-o',str(obj)],check=True)
    subprocess.run(command,cwd=source,check=True)
    twin = Elf(binary)
    if text(twin)[5] == target: break
    gap += target-text(twin)[5]
else: raise RuntimeError('text size did not converge')
def symbols(elf):
    sec=elf.names.index('.text')
    return Counter((s['name'],s['value'],s['size']) for s in elf.symbols if s['info']&15==2 and s['sec']==sec)
assert not symbols(before)-symbols(twin), 'padding moved an aligned-baseline function'
assert len(symbols(twin)-symbols(before)) == 1
twin_note=twin.sections[twin.names.index('.note.gnu.property')]
assert twin.data[twin_note[4]:twin_note[4]+twin_note[5]] == properties
subprocess.run(['strip','--strip-debug',str(binary)],check=True)
receipt=dict(kind='A: behavior twin', behavior='fc138d82e integrated wave-5 POST (WB4.1 park present)',
    source_ref='fc138d82e', baseline_sha256=sha(baseline), candidate_sha256=sha(candidate),
    pad_sha256=sha(binary), aligned_sha256=sha(aligned), baseline_text=text(Elf(baseline))[5],
    candidate_text=target, aligned_text=text(before)[5], pad_text=text(twin)[5],padding_bytes=gap,
    flags=flags, build=build, link=command,
    limitation='Equal total .text size only. Function alignment/placement differs from original wave-5 POST and fallback.',
    padding_preserves_aligned_function_addresses_sizes=True,
    baseline_rebuild_proof='docs/wave5b/base-rebuild-identity.json')
(ROOT/'docs/wave5b/pad-a.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
