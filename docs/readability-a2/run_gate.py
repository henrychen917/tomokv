#!/usr/bin/env python3
"""Replay A1's selected correctness jobs on the A2 CPU/port allocation."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/readability-a2'
previous = json.loads((ROOT / 'docs/readability-a1/evidence/gate-runs.json').read_text())
jobs = sorted(set(previous['latest_jobs']) - {'release', 'production_units', 'racefix_tsan_build'}
              | {'witness_contracts', 'bugs5', 'flip'})
env = dict(os.environ, LC_ALL='C', TOMO_INFO_GIT_SHA1='5c363128', TOMO_INFO_GIT_DIRTY='0',
           GATE_TEST_PORT='25199', GATE_PROOF_NO_RATES='1', GATE_ONLY_JOBS=' '.join(jobs))
command = ['taskset', '-c', '0-47', 'tests/gate.sh', 'iteration',
           '--server-cores', '0-31', '--load-cores', '32-47', '--load-smt', '',
           '--ports', '25100-25198']
record = dict(command=command, jobs=jobs, environment={k: env[k] for k in env
              if k.startswith(('GATE_', 'TOMO_INFO_')) or k == 'LC_ALL'})
(OUT / 'gate-command.json').write_text(json.dumps(record, indent=2) + '\n')
with (OUT / 'gate.log').open('w') as log:
    result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
record['exit'] = result.returncode
(OUT / 'gate-command.json').write_text(json.dumps(record, indent=2) + '\n')
print('selected gate exit', result.returncode, flush=True)
raise SystemExit(result.returncode)
