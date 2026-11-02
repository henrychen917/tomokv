#!/usr/bin/env python3
"""Run the remaining mode/engine legs through the gate's selected-job interface."""
import json
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cmdfix2'


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    jobs = [
        ('post-fused-uring', 'uring', 1, 'debug-0 debug-1 atomic_batteries release_batteries'),
        ('post-fused-epoll', 'epoll', 1, 'debug-0 debug-1 atomic_batteries release_batteries'),
        ('post-modes-epoll', 'epoll', 0,
         'debug-0 debug-1 fused-0 fused-1 txn_group_fused txn_group_split '
         'txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1'),
    ]
    tag = os.environ.get('CMDFIX2_RUN_TAG', '')
    assert not tag or tag == 'v2'
    if tag:
        jobs += [
            ('post-extra-uring', 'uring', 0,
             'rootcompat-stringlimit datafix1_bitfield datafix1_locale authfix atomic_floor perfio_stream'),
            ('post-tcl-receipted-uring', 'uring', 0, 'redis_tcl'),
            ('post-tcl-receipted-epoll', 'epoll', 0, 'redis_tcl'),
        ]
    results = []
    for label, engine, fused, selected in jobs:
        if tag: label = label.replace('post-', 'post-'+tag+'-', 1)
        command = ['taskset', '-c', '100-111', 'tests/gate.sh', 'quick',
                   '--server-cores', '100-107', '--load-cores', '108-111', '--load-smt', '',
                   '--ports', '21390-21399', '--candidate-binary', str(OUT/'POST')]
        changes = dict(LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis', GATE_ONLY_JOBS=selected,
                       GATE_PROOF_NO_RATES='1', GATE_NET_IO=engine, GATE_TXN_FUSED=str(fused),
                       GATE_TCL_MANIFEST='docs/cmdfix2/tcl-manifest.json',
                       CXX='g++ -gz=zlib', CC='cc -gz=zlib', GATE_LEDGER=str(OUT/label))
        with (OUT/(label+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **changes),
                                    stdout=log, stderr=subprocess.STDOUT)
        results.append(dict(label=label, command=command, environment=changes, exit_code=result.returncode,
                            candidate_sha256=hashlib.sha256((OUT/'POST').read_bytes()).hexdigest()))
        (OUT/('more-jobs'+('-'+tag if tag else '')+'.json')).write_text(json.dumps(results, indent=2)+'\n')
        print(label, result.returncode, flush=True)
    raise SystemExit(int(any(row['exit_code'] for row in results)))
