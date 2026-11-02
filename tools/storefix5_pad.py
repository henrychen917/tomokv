#!/usr/bin/env python3
"""PAD-A: PRE behavior, POST's cold helper size and aggregate .text extent."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--post', type=Path, required=True)
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
pre = ROOT/'build/storefix5/pre-source'
out = ROOT/'build/storefix5/pad-a'
out.mkdir(parents=True, exist_ok=True)
os.environ['LC_ALL'] = 'C'

def section(binary):
    text = subprocess.check_output(['size', '-A', str(binary)], text=True)
    return tuple(map(int, re.search(r'^\.text\s+(\d+)\s+(\d+)$', text, re.M).groups()))

recipe = subprocess.check_output(['make', '-n', '-W', 'src/cmd/xshard.cc',
                                 '-W', 'build/src/main.o', 'all'], cwd=pre, text=True)
cmd = shlex.split(next(line for line in recipe.splitlines() if ' -o build/tomokv ' in line))
cmd = [str(pre/arg) if arg.endswith(('.o','.a')) and not Path(arg).is_absolute() else arg for arg in cmd]
cmd += ['-Wl,--compress-debug-sections=zlib']

# Preserve all PRE algorithms and the original field offsets, while matching
# the candidate's additional cold request state, construction and destruction.
# This is a private source copy: the frozen PRE source and objects stay intact.
layout_source = out/'source'
shutil.copytree(pre/'src', layout_source/'src', dirs_exist_ok=True)
third_party = layout_source/'third_party'
if not third_party.exists():
    third_party.symlink_to(pre/'third_party', target_is_directory=True)
scatter = layout_source/'src/cmd/scatter_engine.inc'
content = scatter.read_text()
old = '    std::unique_ptr<DatabaseStatsTable> database_stats;\n};'
new = '''    std::unique_ptr<DatabaseStatsTable> database_stats;
    struct LayoutTwinCursor {
        uint64_t cursor = 0;
        uint64_t seen = 0;
        std::string key;
        bool started = false;
    } randomkey;
};
static_assert(sizeof(GroupAux) == 136);
'''
assert content.count(old) == 1
scatter.write_text(content.replace(old, new))
compiles = []
for line in recipe.splitlines():
    if ' -c src/cmd/xshard.cc ' not in line:
        continue
    build = shlex.split(line)
    original = pre/build[build.index('-o')+1]
    target = out/('db0-xshard.o' if '/db0/' in str(original) else 'xshard.o')
    build[build.index('-o')+1] = str(target)
    build += ['-gz=zlib']
    cmd[cmd.index(str(original))] = str(target)
    compiles.append(build)
assert len(compiles) == 2, compiles

def compile_one(argv):
    with Path(argv[argv.index('-o')+1]).with_suffix('.log').open('w') as log:
        subprocess.run(argv, cwd=layout_source, stdout=log, stderr=subprocess.STDOUT, check=True)

with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(compile_one, compiles))
cmd[cmd.index('-o')+1] = str(out/'layout-base')
subprocess.run(cmd, cwd=pre, check=True)
old_size, old_start = section(out/'layout-base')
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
cmd[cmd.index('-o')+1] = str(out/'tomokv')
cmd += [str(out/'padding.o')]
subprocess.run(cmd, cwd=pre, check=True)
assert section(out/'tomokv') == (new_size, new_start)
sha = lambda path: hashlib.file_digest(Path(path).open('rb'), 'sha256').hexdigest()
record = dict(kind='A: PRE behavior, matching POST cold GroupAux layout and aggregate .text extent',
              limitation='Per-function addresses are not matched to POST; the control cannot isolate every code-placement effect.',
              pre_sha256=sha(pre/'build/tomokv'), post_sha256=sha(a.post),
              pad_sha256=sha(out/'tomokv'), text_start=new_start, text_size=new_size,
              padding_bytes=delta, groupaux_bytes=136, compile=compiles,
              source_sha256=sha(scatter), layout_base_sha256=sha(out/'layout-base'), argv=cmd)
(ROOT/'docs/storefix5/pad-a.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2))
