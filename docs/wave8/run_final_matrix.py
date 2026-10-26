#!/usr/bin/env python3
"""Final POST correctness campaign through gate.sh's whole-job selector only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 96)))
matrix = json.loads((ROOT / 'docs/wave8/correctness-matrix.json').read_text())
extra = json.loads((ROOT / 'docs/wave8/supplemental-matrix.json').read_text())
campaign = [('final-lanes', matrix['once'][:14], []),
            ('final-tcl', ['compat2'], []),
            ('final-tcl-planted', ['compat2'], ['--binary', 'build/wave8/planted/tomokv']),
            ('final-units', matrix['once'][14:], []),
            ('final-supplemental', [j for j in extra['once'] if j not in matrix['once']], [])]
for engine in ('uring', 'epoll'):
    campaign.append(('final-engine-' + engine, matrix['each_engine'] + extra['each_engine'], ['--engine', engine]))
    for fused in (False, True):
        mode = '1s' if fused else '2s'
        opts = ['--engine', engine] + (['--fused'] if fused else [])
        campaign.append((f'final-debug-{engine}-{mode}', matrix['each_mode_engine'] + extra['each_mode_engine'], opts))
    campaign.append(('final-differ-' + engine, matrix['differ_each_engine'], ['--engine', engine]))
for fused in (False, True):
    campaign.append(('final-persistence-' + ('1s' if fused else '2s'), extra['each_mode'],
                     ['--fused'] if fused else []))
sha = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
outcomes = []
for name, jobs, options in campaign:
    receipt = ROOT / 'docs/wave8/jobs' / (name + '.json')
    argv = ['python3', 'docs/wave8/run_jobs.py', name, *jobs, '--single-slot', *options]
    assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == sha
    if not receipt.exists():
        print('START', name, flush=True)
        subprocess.run(argv, cwd=ROOT)
    data = json.loads(receipt.read_text())
    if '--binary' not in options:
        assert data['binary_sha256'] == sha
    assert data['binary_unchanged']
    outcomes.append(dict(name=name, exit=data['exit'], summary=data['summary']))
    (ROOT / 'docs/wave8/final-campaign.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    print('DONE', name, data['exit'], flush=True)
