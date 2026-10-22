#!/usr/bin/env python3
"""Measure every command of job_abba_selftest without its row watchdog."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/wave4'))
import run_proof

label = sys.argv[1]
out = ROOT / 'docs/wave4c/timing' / label
out.mkdir(parents=True, exist_ok=False)
env = run_proof.setup()
env['WAVE4C_TIMINGS'] = str(out)
text = (ROOT / 'tests/gate.sh').read_text().split('job_abba_selftest(){', 1)[1].split('\n}', 1)[0]
commands = [shlex.split(m[1]) for m in re.finditer(r'^py (tests/[^>\n]+?)\s*>>?\s*\$TMPDIR/', text, re.M)]
assert len(commands) == 15, commands
rows = []
for command in commands:
    start = time.monotonic()
    argv = ['/usr/bin/python3', str(ROOT / 'docs/wave4c/time_suite.py'), *command]
    with (out / (Path(command[0]).stem + '.log')).open('w') as stream:
        status = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
    rows.append(dict(argv=argv, seconds=time.monotonic() - start, returncode=status))
    (out / 'suites.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(command, status, rows[-1]['seconds'], flush=True)
raise SystemExit(any(r['returncode'] for r in rows))
