#!/usr/bin/env python3
"""Serial gate-job campaign; failed attempts remain in their original receipts."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(64, 96)))
matrix = json.loads((ROOT / 'docs/wave8/correctness-matrix.json').read_text())
done = {
    'source_identity', 'lualibs', 'latencyfix_grammar', 'latencyfix_shape',
    'latencyfix_off', 'iofix-deferred', 'iofix-hz', 'iofix-sleep',
    'iofix-signal', 'execfair', 'reorder_identity',
}
campaign = [('remaining-once', [j for j in matrix['once'] if j not in done], [])]
for engine in ('uring', 'epoll'):
    campaign.append(('engine-' + engine, matrix['each_engine'], ['--engine', engine]))
    for fused in (False, True):
        campaign.append((f'debug-{engine}-' + ('1s' if fused else '2s'),
                         matrix['each_mode_engine'],
                         ['--engine', engine] + (['--fused'] if fused else [])))
    campaign.append(('differ-' + engine, matrix['differ_each_engine'], ['--engine', engine]))
campaign.append(('tcl-planted-geo', ['compat2'], ['--binary', 'build/wave8/planted/tomokv']))
outcomes = []
for name, jobs, options in campaign:
    receipt = ROOT / 'docs/wave8/jobs' / (name + '.json')
    argv = ['python3', 'docs/wave8/run_jobs.py', name, *jobs, '--single-slot', *options]
    if not receipt.exists():
        print('START', name, flush=True)
        result = subprocess.run(argv, cwd=ROOT)
    data = json.loads(receipt.read_text())
    outcomes.append(dict(name=name, exit=data['exit'], summary=data['summary']))
    (ROOT / 'docs/wave8/campaign.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    print('DONE', name, data['exit'], flush=True)
