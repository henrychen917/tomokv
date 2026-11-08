#!/usr/bin/env python3
"""Run the auditors' owned tests with confined resources and POST expectations.

Copies live only in the lane's build tree. Source hashes and exact adaptations
are retained; the round5-read tree is never edited.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import subprocess

SOURCE = Path('/home/user/Projects/round5-read/tests')
CASES = {
    'tls-watch': ('ex-path', ['t02_tls_watch_borrow.py', 't20_tls_tracking_watch_crash.py',
                             't20b_tls_single_conn_crash.py', 't20d_tls12_ktls_crash.py']),
    'exclusive': ('net', ['t17_double_boot.py']),
    'fds': ('net', ['t12_maxclients_fdlimit.py', 't12b_fd_reserve.py', 't12c_fd_reserve_hang.py']),
    'tls-idle': ('net', ['t01_tls_idle_timeout.py', 't21_net_bytes.py']),
    'boot': ('io-loop', ['t02_aof_bind_failure.py', 't02b_aof_bind_banner.sh', 't03_banner_race.py']),
    'boot-banner-net': ('net', ['t08_banner_race.py']),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=CASES, required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert a.cores in ('8-15', '8,9,10,11,12,13,14,15'), a.cores
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    binary = Path(a.binary).resolve()
    (root / 'arm.json').write_text(json.dumps(dict(
        binary=str(binary), sha256=hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest(),
        cores=a.cores, affinity=sorted(os.sched_getaffinity(0)), locale='C'), indent=2) + '\n')
    scratch = root / 'work'
    scratch.mkdir(exist_ok=True)
    group, scripts = CASES[a.case]
    helper = {'net': 'netlib.py', 'ex-path': 'lib.py', 'io-loop': 'resp.py'}[group]
    receipts = []
    for filename in [helper] + scripts:
        original = (SOURCE / group / filename).read_text()
        edited = original.replace('/home/user/Projects/bench-bins/tomokv-headline-105c5818cc',
                                  str(Path(a.binary).resolve()))
        edited = edited.replace('64-79', a.cores)
        edited = re.sub(r'range\(64,\s*80\)', 'range(8, 16)', edited)
        edited = re.sub(r'\b22[025](\d\d)\b', lambda m: '211' + m[1], edited)
        edited = re.sub(r"SCRATCH = '[^']+'", 'SCRATCH = ' + repr(str(scratch)), edited)
        if filename.endswith('.sh'):
            edited = re.sub(r'^D=.*$', 'D=' + shlex.quote(str(scratch / 't02x')), edited, flags=re.M)
            # The audit shell reported grep's status; retain its transcript and
            # record the actual server status, with bash's PIPESTATUS.
            edited = edited.replace('echo "rc=$?"', 'echo "rc=${PIPESTATUS[0]}"')
        if group == 'ex-path':
            # Audit assertions describe broken PRE. Promote only those predicates;
            # exact data/control, kTLS and liveness checks remain in their tests.
            edited = edited.replace('res[0] == "died" and not alive and rc == -6',
                                    'res == ("replied", True) and alive and rc == 0')
            edited = edited.replace('server aborts', 'server replies and survives')
            edited = edited.replace('z2[0] - z1[0] == N', 'z2[0] - z1[0] == 0')
            edited = edited.replace('TLS GET took a FlatStore borrow (plaintext handler_notify)',
                                    'TLS GET took no FlatStore borrow')
            if filename == helper:
                edited = edited.replace('return not bad', 'assert not bad, bad\n        return True')
        dest = root / filename
        dest.write_text(edited)
        receipts.append(dict(source=str(SOURCE / group / filename),
                             source_sha256=hashlib.sha256(original.encode()).hexdigest(),
                             adapted_sha256=hashlib.sha256(edited.encode()).hexdigest()))
        (root / (filename + '.diff')).write_text(''.join(difflib.unified_diff(
            original.splitlines(True), edited.splitlines(True), fromfile='audit/' + filename,
            tofile='confined-POST/' + filename)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for filename in scripts:
        cmd = ['taskset', '-c', a.cores, 'bash' if filename.endswith('.sh') else 'python3', str(root / filename)]
        with (root / (filename + '.log')).open('w') as log:
            run = subprocess.run(cmd, cwd=root, env=dict(os.environ, LC_ALL='C'),
                                 stdout=log, stderr=subprocess.STDOUT, timeout=420)
        receipts.append(dict(script=filename, command=cmd, exit=run.returncode))
        print(filename, 'exit', run.returncode, flush=True)
        (root / 'receipt.json').write_text(json.dumps(receipts, indent=2))
        assert run.returncode == 0, filename
        if filename.endswith('.sh'):
            log = (root / (filename + '.log')).read_text()
            assert 'rc=1\n' in log and 'port-closed' in log, log
            assert 'listening on' not in log, log


if __name__ == '__main__':
    main()
