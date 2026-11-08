#!/usr/bin/env python3
"""Twenty real gate job invocations; preserve failures and every final ledger."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/readability-a1b/flip-repeat'
OUT.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, LC_ALL='C', TOMO_INFO_GIT_SHA1='5c363128', TOMO_INFO_GIT_DIRTY='0',
           GATE_TEST_PORT='25199', GATE_PROOF_NO_RATES='1', GATE_ONLY_JOBS='flip')
command = ['taskset', '-c', '64-79', 'tests/gate.sh', 'iteration',
           '--server-cores', '64-71', '--load-cores', '72-79', '--load-smt', '', '--ports', '25100-25119']
records = []
for i in range(1, 21):
    log = OUT / f'{i:02d}.log'
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text()
    run = next((line.split('artifacts: ', 1)[1] for line in text.splitlines() if 'artifacts: ' in line), None)
    records.append(dict(iteration=i, returncode=result.returncode, log=str(log.relative_to(ROOT)), run=run))
    (OUT / 'results.json').write_text(json.dumps(dict(command=command, env={k:env[k] for k in (
        'LC_ALL', 'TOMO_INFO_GIT_SHA1', 'TOMO_INFO_GIT_DIRTY', 'GATE_TEST_PORT', 'GATE_PROOF_NO_RATES', 'GATE_ONLY_JOBS')},
        records=records), indent=2) + '\n')
    print(f'flip repetition {i}/20: exit {result.returncode}, {run}', flush=True)
raise SystemExit(any(r['returncode'] for r in records))
