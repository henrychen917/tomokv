#!/usr/bin/env python3
"""Complete related command-family jobs through the gate's own interface."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cmdfix2'


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    # These jobs bind sibling unit binaries to build/tomokv. Require the frozen
    # POST bytes before using that canonical path, rather than copying units.
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(ROOT/'build/tomokv') == digest(OUT/'POST')
    selected = (
        'pubtrackfix clientfix compat2 compat3 blockfix2 blockfix_structure '
        'blockfix_registry datafix2_encoding datafix2_watch netcmd_units '
        'rootcompat-sort-acl rootcompat-redact rootcompat-xsnotify rootcompat-setpast '
        'dispatch_arity dispatch_errors dispatch_children '
        + ' '.join('at412-'+case for case in (
            'T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16 owner').split()))
    jobs = [('post-related', 'uring', 0, selected)]
    jobs.extend((f'post-notify-{engine}-{mode}', engine, mode == '1s', 'notify')
                for engine in ('uring', 'epoll') for mode in ('1s', '2s'))
    results = []
    for label, engine, fused, selection in jobs:
        command = ['taskset', '-c', '100-111', 'tests/gate.sh', 'quick',
                   '--server-cores', '100-107', '--load-cores', '108-111', '--load-smt', '',
                   '--ports', '21380-21389', '--candidate-binary', str(ROOT/'build/tomokv')]
        changes = dict(LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
                       GATE_ONLY_JOBS=selection, GATE_PROOF_NO_RATES='1',
                       GATE_NET_IO=engine, GATE_TXN_FUSED=str(int(fused)),
                       GATE_TCL_MANIFEST='docs/cmdfix2/tcl-manifest.json',
                       CXX='g++ -gz=zlib', CC='cc -gz=zlib', GATE_LEDGER=str(OUT/label))
        with (OUT/(label+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **changes),
                                    stdout=log, stderr=subprocess.STDOUT)
        results.append(dict(label=label, command=command, environment=changes,
                            exit_code=result.returncode))
        (OUT/'related-jobs.json').write_text(json.dumps(results, indent=2)+'\n')
        print(label, result.returncode, flush=True)
    raise SystemExit(int(any(row['exit_code'] for row in results)))
