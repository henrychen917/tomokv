#!/usr/bin/env python3
"""Final POST correctness campaign through gate.sh's whole-job selector only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import concurrent.futures
import shutil
import time

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
def run(item, slot=None):
    name, jobs, options = item
    receipt = ROOT / 'docs/wave8/jobs' / (name + '.json')
    argv = ['python3', 'docs/wave8/run_jobs.py', name, *jobs, '--single-slot', *options]
    if slot is not None:
        argv += ['--server-start', str(64 + slot*8), '--port', str(20020 + slot*20),
                 '--asan-binary', str(ROOT / 'build/tomokv-wave8-ASAN')]
    assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == sha
    if not receipt.exists():
        log = receipt.with_suffix('.log')
        if log.exists():
            # Independently launched standard differential folds may still own
            # this name. Never overlap it or replace an incomplete attempt.
            until = time.monotonic() + 7200
            while not receipt.exists() and time.monotonic() < until:
                time.sleep(10)
            assert receipt.exists(), ('existing attempt has no completion receipt', name)
        else:
            print('START', name, flush=True)
            subprocess.run(argv, cwd=ROOT)
    data = json.loads(receipt.read_text())
    if '--binary' not in options:
        assert data['binary_sha256'] == sha
    assert data['binary_unchanged']
    print('DONE', name, data['exit'], flush=True)
    return dict(name=name, exit=data['exit'], summary=data['summary'])

outcomes = []
def save(result):
    outcomes.append(result)
    (ROOT / 'docs/wave8/final-campaign.json').write_text(json.dumps(outcomes, indent=2) + '\n')

# All shared object/cache builds finish serially. Later jobs reuse the frozen
# ASAN arm via the gate's explicit partial-job interface, so no linker can
# truncate an instrumented binary while another job executes it.
for item in campaign[:5]:
    save(run(item))
asan = ROOT / 'build/tomokv-wave8-ASAN'
shutil.copy2(ROOT / 'build/gate-cache/tomokv-asan', asan)
(ROOT / 'docs/wave8/frozen-asan.json').write_text(json.dumps(dict(
    path=str(asan), sha256=hashlib.sha256(asan.read_bytes()).hexdigest(),
    reason='Instrumented final source; avoids shared cache relinking during independent gate jobs.'), indent=2) + '\n')
groups = [[], [], []]
for item in campaign[5:]:
    name = item[0]
    if name == 'final-differ-uring' or name.startswith('final-debug-uring') or name == 'final-persistence-2s':
        slot = 1
    elif 'epoll' in name:
        slot = 2
    else:
        slot = 0
    groups[slot].append(item)
for items in groups:
    items.sort(key=lambda item: not item[0].startswith('final-differ-'))
def group(slot):
    return [run(item, slot) for item in groups[slot]]
with concurrent.futures.ThreadPoolExecutor(3) as pool:
    futures = [pool.submit(group, slot) for slot in range(3)]
    for future in concurrent.futures.as_completed(futures):
        for result in future.result():
            save(result)
