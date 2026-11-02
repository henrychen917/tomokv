#!/usr/bin/env python3
"""PAD-A: PRE behavior with POST's aggregate .text extent (not per-function layout)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--post', type=Path, required=True)
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
pre = ROOT/'build/storefix5/pre-source'
out = ROOT/'build/storefix5/pad-a'
out.mkdir(parents=True, exist_ok=True)

def section(binary):
    text = subprocess.check_output(['size', '-A', str(binary)], text=True)
    return tuple(map(int, re.search(r'^\.text\s+(\d+)\s+(\d+)$', text, re.M).groups()))

old_size, old_start = section(pre/'build/tomokv')
new_size, new_start = section(a.post)
assert new_start == old_start and new_size >= old_size, 'this PAD requires a growing .text'
delta = new_size-old_size
source = out/'padding.S'
source.write_text('.section .text\n.global tomo_storefix5_pad_a_text\n'
                  '.type tomo_storefix5_pad_a_text,@function\n'
                  'tomo_storefix5_pad_a_text:\n'+f'.fill {delta},1,0x90\n'
                  '.size tomo_storefix5_pad_a_text,.-tomo_storefix5_pad_a_text\n'
                  # Preserve the CET properties of every production object;
                  # otherwise ld removes .plt.sec and shifts all text.
                  '.section .note.gnu.property,"a"\n.p2align 3\n'
                  '.long 4\n.long 16\n.long 5\n.asciz "GNU"\n'
                  '.long 0xc0000002\n.long 4\n.long 3\n.long 0\n'
                  '.section .note.GNU-stack,"",@progbits\n')
subprocess.run(['gcc', '-c', str(source), '-o', str(out/'padding.o')], check=True)
recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'],
                                 cwd=pre, text=True)
cmd = shlex.split(next(line for line in recipe.splitlines() if ' -o build/tomokv ' in line))
cmd = [str(pre/arg) if arg.endswith(('.o','.a')) and not Path(arg).is_absolute() else arg for arg in cmd]
cmd[cmd.index('-o')+1] = str(out/'tomokv')
cmd += [str(out/'padding.o'), '-Wl,--compress-debug-sections=zlib']
subprocess.run(cmd, cwd=pre, check=True)
assert section(out/'tomokv') == (new_size, new_start)
sha = lambda path: hashlib.file_digest(Path(path).open('rb'), 'sha256').hexdigest()
record = dict(kind='A: PRE behavior, matching POST aggregate .text extent',
              limitation='Per-function addresses remain PRE; this is not an exact per-function layout twin.',
              pre_sha256=sha(pre/'build/tomokv'), post_sha256=sha(a.post),
              pad_sha256=sha(out/'tomokv'), text_start=new_start, text_size=new_size,
              padding_bytes=delta, argv=cmd)
(ROOT/'docs/storefix5/pad-a.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2))
