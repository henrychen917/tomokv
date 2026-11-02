#!/usr/bin/env python3
"""Serialize the remaining PAD, falsifier and selected-job proofs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
output = DOC / 'finish-proof.json'
receipt = dict(waiting_for='main and quiet queues', stages=[])


def save():
    output.write_text(json.dumps(receipt, indent=2) + '\n')


def run(label, argv, expected=(0,)):
    row = dict(label=label, argv=argv, expected=list(expected), started=time.time())
    receipt['stages'].append(row)
    save()
    with (DOC / (label + '.log')).open('w') as log:
        result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    row.update(exit=result.returncode, finished=time.time())
    save()
    print(label, result.returncode, flush=True)
    assert result.returncode in expected, row


save()
while True:
    try:
        main = json.loads((DOC / 'final-proof.json').read_text())
        quiet = json.loads((DOC / 'quiet-final-retry.json').read_text())
        if main.get('complete') and 'exit' in quiet:
            break
    except json.JSONDecodeError:
        pass
    time.sleep(5)
receipt['waiting_for'] = None
save()

pad = ROOT / 'build/storefix5/pad-a'
assert not (pad / 'extent-only-tomokv').exists(), 'preserve each old PAD exactly once'
shutil.copy2(pad / 'tomokv', pad / 'extent-only-tomokv')
shutil.copy2(DOC / 'pad-a.json', DOC / 'pad-extent-only.json')
for mode in ('1s', '2s'):
    for suffix in ('.json', '.log', '.server.log'):
        shutil.copy2(DOC / ('pad-final-' + mode + suffix),
                     DOC / ('pad-extent-only-' + mode + suffix))
run('pad-layout-build-final', ['python3', 'tools/storefix5_pad.py', '--post', 'build/storefix5/POST'])
for mode in ('1s', '2s'):
    path = DOC / f'pad-final-{mode}.json'
    run(f'pad-final-{mode}', ['python3', 'tools/storefix5_checks.py', '--binary',
        'build/storefix5/PAD-A', '--mode', mode, '--port', '21600', '--cases',
        'randomkey,idle,append', '--output', str(path)], (1,))
    data = json.loads(path.read_text())
    cases = data['cases']
    assert data['exit'] == 0 and not data.get('forced_stop')
    assert set(cases) == {'randomkey', 'idle', 'append'}, cases
    assert not cases['randomkey']['passed'] and not cases['idle']['passed'], cases
    assert cases['append']['passed'], cases

arms = ''.join(hashlib.sha256((ROOT / 'build/storefix5' / name).read_bytes()).hexdigest()
               + '  ' + name + '\n' for name in ('PRE', 'POST', 'PAD-A'))
(DOC / 'ARMS.sha256').write_text(arms)
(ROOT / 'build/storefix5/ARMS.sha256').write_text(arms)
run('sampler-controls-final', ['python3', 'tools/storefix5_retirement.py'])
run('mode-equivalence-pin-final', ['python3', 'tests/mode_equivalence.py', '--self-test'])
os.environ['GATE_TEST_PORT'] = '21699'
run('gates-test-final', ['python3', 'tests/gates_test.py'])
run('inventory-driver-final', ['python3', 'tools/storefix5_inventory_proof.py'], (0, 1))

freshness = []
for prior in json.loads((DOC / 'production-units-release.json').read_text())['freshness']:
    result = subprocess.run(prior['argv'], cwd=ROOT, capture_output=True, text=True)
    freshness.append(dict(argv=prior['argv'], exit=result.returncode,
                          output=result.stdout + result.stderr))
(DOC / 'freshness-final.json').write_text(json.dumps(freshness, indent=2) + '\n')
receipt['freshness_passed'] = sum(r['exit'] == 0 for r in freshness)
receipt['complete'] = True
save()
assert all(r['exit'] == 0 for r in freshness), freshness
