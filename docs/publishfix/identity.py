#!/usr/bin/env python3
"""Run all three requested identity tools; differences are evidence, not a veto."""
import argparse
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('label')
a = p.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
out = root / 'docs/publishfix/identity' / a.label
out.mkdir(parents=True, exist_ok=False)
pre = root / 'build/publishfix/pre/objects'
post = root / 'build'
commands = {
    'lbstall': ['tools/lbstall_artifacts.py', 'compare', pre, post, out / 'hot.json'],
    'ccfix': ['tools/ccfix_audit.py', pre, post, out / 'full'],
    'linked': ['docs/deadswitch/linked_bytes.py', pre / 'tomokv', post / 'tomokv', out / 'linked.json'],
}
exits = {}
for name, command in commands.items():
    argv = ['taskset', '-c', '96-111', 'python3', *map(str, command)]
    with (out / (name + '.log')).open('w') as f:
        exits[name] = subprocess.run(argv, cwd=root, stdout=f, stderr=subprocess.STDOUT).returncode
    print(name, exits[name], flush=True)
(out / 'exits.json').write_text(json.dumps(exits, indent=2) + '\n')
