#!/usr/bin/env python3
"""PAD A: PRE behavior with POST's total .text size; no placement claim."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / 'build/wave5/pre-source'
OUT = ROOT / 'build/wave5/pad-a'
OUT.mkdir(parents=True, exist_ok=True)
def text_size(path):
    rows = subprocess.check_output(['size', '-A', str(path)], text=True).splitlines()
    return next(int(s.split()[1]) for s in rows if s.startswith('.text '))

target = text_size(ROOT / 'build/tomokv')
before = text_size(PRE / 'build/tomokv')
gap = target - before
assert gap > 0
link = shlex.split(next(s for s in reversed((ROOT / 'build/wave5/build-pre.log').read_text().splitlines())
                       if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
for i, arg in enumerate(link):
    if arg.startswith('build/') and arg.endswith('.o'):
        link[i] = str(PRE / arg)
binary = ROOT / 'build/tomokv-wave5-PAD-A'
link[link.index('-o') + 1] = str(binary)
link += [str(OUT / 'pad.o'), '-Wl,--strip-debug']
for attempt in range(3):
    (OUT / 'pad.S').write_text('.text\n.balign 1\n.globl wave5_pad_a\n'
        '.type wave5_pad_a,@function\nwave5_pad_a:\n.fill ' + str(gap) + ',1,0x90\n'
        '.size wave5_pad_a,.-wave5_pad_a\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['g++', '-c', str(OUT / 'pad.S'), '-o', str(OUT / 'pad.o')], check=True)
    subprocess.run(link, cwd=ROOT, check=True)
    actual = text_size(binary)
    if actual == target:
        break
    gap += target - actual
else:
    raise RuntimeError('PAD text size did not converge')
headline = Path('/home/user/Projects/bins/txnorder2-pre-97ea4e06')
shutil.copy2(headline, ROOT / 'build/tomokv-wave5-PRE')
receipt = dict(kind='A: behaviour twin', scope='PRE behavior; POST total .text size only, not per-body placement or data layout',
               pre_text=before, post_text=target, pad_text=actual, padding_bytes=gap,
               link=link, arms={})
for name, path in [('PRE', ROOT / 'build/tomokv-wave5-PRE'), ('POST', ROOT / 'build/tomokv'), ('PAD-A', binary)]:
    receipt['arms'][name] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
(ROOT / 'docs/wave5/pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt['arms'], indent=2))
