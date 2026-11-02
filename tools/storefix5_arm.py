#!/usr/bin/env python3
"""Link an isolated arm from production objects and explicit cold-unit trials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('arm')
p.add_argument('--normal', type=Path, required=True)
p.add_argument('--db0', type=Path, required=True)
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
output = ROOT/'build/storefix5/arms'/a.arm
output.mkdir(parents=True, exist_ok=True)
recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'],
                                 cwd=ROOT, text=True)
link = shlex.split(next(line for line in recipe.splitlines() if ' -o build/tomokv ' in line))
for i, arg in enumerate(link):
    if arg.startswith('build/') and arg.endswith(('.o', '.a')):
        relative = Path(arg).relative_to('build')
        dest = output/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        source = (a.normal if str(relative)=='src/cmd/xshard.o' else
                  a.db0 if str(relative)=='db0/src/cmd/xshard.o' else ROOT/arg).resolve()
        dest.unlink(missing_ok=True)
        dest.symlink_to(source)
        link[i] = str(dest)
link[link.index('-o')+1] = str(output/'tomokv')
link += ['-Wl,--compress-debug-sections=zlib']
subprocess.run(link, cwd=ROOT, check=True)
doc = ROOT/'docs/storefix5/budgets'/(a.arm+'-link.json')
doc.write_text(json.dumps(dict(argv=link, sha256=hashlib.file_digest(
    (output/'tomokv').open('rb'), 'sha256').hexdigest()), indent=2)+'\n')
