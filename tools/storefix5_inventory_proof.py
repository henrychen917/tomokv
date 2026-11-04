#!/usr/bin/env python3
"""Complete related-job coverage after the main and quiet proof queues stop."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
receipt = {'stages': []}
output = DOC / 'inventory-proof.json'


def save():
    output.write_text(json.dumps(receipt, indent=2) + '\n')


assert json.loads((DOC / 'final-proof.json').read_text()).get('complete'), 'main proof still active'
quiet = json.loads((DOC / 'quiet-final-retry.json').read_text())
assert 'exit' in quiet, 'quiet proof still active'
receipt['paired_units'] = []
for name in ('moverfix-unit', 'moverfix-db0-unit'):
    source = ROOT / 'build' / name
    destination = (ROOT / 'build/storefix5/POST').resolve().parent / name
    assert source.is_file() and os.access(source, os.X_OK), source
    if not destination.exists():
        destination.symlink_to(source)
    assert destination.resolve() == source
    receipt['paired_units'].append(dict(unit=name, source=str(source), paired=str(destination),
        sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
save()
stages = [
    ('gate-equivalence-uring-final', 'differ-equivalence', {'GATE_DIFFER_NET_IO': 'uring'},
     'build/storefix5/POST'),
    ('gate-sampler-final', 'storage_units', {}, 'build/storefix5/POST'),
    ('gate-txn-pairing-final', 'txnorder_wake txnorder2', {}, 'build/storefix5/POST'),
    ('gate-flush-deadline-pre-final', 'flushfix3', {}, 'build/storefix5/PRE'),
    ('gate-flush-deadline-post-final', 'flushfix3', {}, 'build/storefix5/POST'),
    ('gate-fifo-pre-final', 'txnorder_fifo_live', {}, 'build/storefix5/PRE'),
    ('gate-inventory-final',
     'bugs5 moverfix hexpread multifix-1s-uring multifix-1s-epoll multifix-2s-uring multifix-2s-epoll '
     'pubtrackfix compat2 globcase sort rootcompat-setpast rootcompat-hscan rootcompat-xsexpiry '
     'notify notifycompat notify_order clientcompat-pause rootcore-notify '
     'debug-0 debug-1 replyoff', {}, 'build/storefix5/POST'),
    ('gate-inventory-fused-final', 'sort debug-0 debug-1 replyoff asan_batteries zc',
     {'GATE_TXN_FUSED': '1'}, 'build/storefix5/POST'),
    ('gate-feature-product-final',
     ' '.join(f'feature-cell-{mode}-{rl}-{client}-{reorder}-{flip}'
              for mode in ('1s', '2s') for rl in (0, 1) for client in (0, 1)
              for reorder in (0, 1) for flip in (0, 1)) +
     ' feature-cell-split-home-min feature-cell-fused-home-max-nopin feature-cell-split-shards-auto',
     {}, 'build/storefix5/POST'),
]
for label, jobs, extra, binary in stages:
    argv = ['tests/gate.sh', 'iteration', '--server-cores', '16-23', '--load-cores', '16-23',
            '--load-smt', '', '--ports', '21620-21622', '--shared-correctness-cpus',
            '--candidate-binary', binary]
    env = dict(os.environ, GATE_ONLY_JOBS=jobs, GATE_PROOF_NO_RATES='1',
               REDIS74_ROOT='/home/user/Projects/redis', **extra)
    row = {'log': label + '.log', 'argv': argv, 'jobs': jobs, 'environment': extra,
           'started': time.time()}
    receipt['stages'].append(row)
    save()
    with (DOC / row['log']).open('w') as log:
        completed = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    row.update(exit=completed.returncode, finished=time.time())
    save()
    cleanup = DOC / 'data-cleanup.json'
    removed = json.loads(cleanup.read_text())
    for done in (ROOT / 'build').glob('gate-run.*/jobs/*/done'):
        for path in done.parent.rglob('*'):
            if path.is_file() and path.suffix in ('.rdb', '.tomo', '.aof', '.manifest'):
                removed.append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size})
                path.unlink()
    cleanup.write_text(json.dumps(removed, indent=2) + '\n')
    print(label, row['exit'], flush=True)
receipt['complete'] = True
save()
raise SystemExit(any(row['exit'] for row in receipt['stages']))
