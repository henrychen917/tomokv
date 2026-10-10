#!/usr/bin/env python3
"""Focused POST rows, requested legacy batteries and the Redis differential matrix."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from clientfix import CASES, server

OUT = ROOT / 'docs/clientfix'
receipt = []


def run(name, argv, env=None):
    command = ['taskset', '-c', '112-127', *argv]
    path = OUT / (name + '.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as output:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=output,
                                stderr=subprocess.STDOUT)
    receipt.append(dict(name=name, command=command, exit_code=result.returncode))
    (OUT / 'post-proof.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(name, result.returncode, flush=True)


for mode in ('1s', '2s'):
    for case in CASES:
        run(f'post/{case}-{mode}', ['taskset', '-c', '121-127', 'python3',
            'tests/clientfix.py', '--binary', 'build/tomokv', '--port', '25070',
            '--cores', '112-119', '--ratio', '6:2', '--mode', mode, '--case', case])
    for battery in ('tracking', 'pubsub', 'climon', 'climon2', 'geo', 'replyoff_xshard'):
        config = argparse.Namespace(binary=str(ROOT / 'build/tomokv'), port=25071,
                                    cores='112-119', ratio='6:2', mode=mode, oracle=False)
        with server(config, atomic=0, read_local=int(mode == '1s')):
            run(f'batteries/{battery}-{mode}', ['taskset', '-c', '121-127', 'python3',
                f'tests/{battery}.py', '127.0.0.1', '25071'])

for geometry in ('split', 'armed-fused'):
    env = dict(os.environ, REDIS74_ROOT='/tmp/claude-1000/redis74',
               GATE_LOAD_CORES='121-127', GATE_DIFFER_ORACLE_CORES='120',
               GATE_DIFFER_GEOMETRY=geometry,
               GATE_DIFFER_PROOF_SUITES=str(OUT / 'differ-suites.txt'),
               GATE_DIFFER_PROOF_SEEDS=str(OUT / 'differ-seeds.txt'),
               GATE_DIFFER_OUT=str(ROOT / 'build/clientfix' / ('differ-' + geometry)))
    run('differ-' + geometry, ['tests/differ_gate.sh', str(ROOT / 'build/tomokv'),
                              '25074', '25075', '112-119', '6:2'], env)

raise SystemExit(any(row['exit_code'] for row in receipt))
