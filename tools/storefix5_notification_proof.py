#!/usr/bin/env python3
"""Check the accounted-memory notification fixture through complete gate jobs."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
receipt = dict(waiting_for='finish-proof.json complete', stages=[])
output = DOC / 'notification-proof.json'


def save():
    output.write_text(json.dumps(receipt, indent=2) + '\n')


save()
while True:
    try:
        if json.loads((DOC / 'finish-proof.json').read_text()).get('complete'):
            break
    except json.JSONDecodeError:
        pass
    time.sleep(5)
receipt['waiting_for'] = None
save()
for arm in ('PRE', 'POST'):
    for mode in ('2s', '1s'):
        label = f'gate-notify-{arm.lower()}-{mode}-final'
        argv = ['tests/gate.sh', 'iteration', '--server-cores', '16-23', '--load-cores',
                '16-23', '--load-smt', '', '--ports', '21620-21622',
                '--shared-correctness-cpus', '--candidate-binary', 'build/storefix5/' + arm]
        row = dict(log=label + '.log', argv=argv, mode=mode, started=time.time())
        receipt['stages'].append(row)
        save()
        env = dict(os.environ, GATE_ONLY_JOBS='notify', GATE_PROOF_NO_RATES='1',
                   GATE_TXN_FUSED='1' if mode == '1s' else '0')
        with (DOC / row['log']).open('w') as log:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        row.update(exit=result.returncode, finished=time.time())
        save()
        print(label, result.returncode, flush=True)
receipt['complete'] = True
save()
raise SystemExit(any(r['exit'] for r in receipt['stages']))
