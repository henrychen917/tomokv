#!/usr/bin/env python3
"""Compile current witnesses against frozen PRE headers/objects; do not rebuild PRE."""
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / 'build/compat2/pre-source'
commands = []
for target, source, output in [
    ('ktls-lifetime-unit', 'ktls_lifetime_unit.cc', 'ktls-lifetime-pre'),
    ('expire-notify-unit', 'expire_notify_unit.cc', 'expire-notify-pre'),
]:
    plan = subprocess.check_output(['make', '-Bn', 'build/' + target], cwd=ROOT, text=True)
    choices = [shlex.split(line) for line in plan.splitlines()
               if line.startswith('g++ ') and ('tests/' + source) in line]
    assert len(choices) == 1
    argv = choices[0]
    argv = [str(ROOT / x) if x == 'tests/' + source else x for x in argv
            if x != 'build/src/cmd/autharity.o']
    argv[argv.index('-o') + 1] = str(ROOT / 'build/compat2' / output)
    commands.append(argv)
    subprocess.run(argv, cwd=PRE, check=True)
(ROOT / 'docs/compat2/pre-unit-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
