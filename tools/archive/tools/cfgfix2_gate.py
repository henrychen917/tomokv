#!/usr/bin/env python3
"""Run selected tests/gate.sh jobs for lane cfgfix2 and archive the partial receipt.

Correctness only: CPUs 32-47 (pool a: server 32-39, load 40-47, ports 21800-21849;
pool b mirrors it on ports 21850-21899), LC_ALL=C.
No rate scoring, ABBA, NIC or full tier. Usage:
  tools/cfgfix2_gate.py PHASE --binary PATH [--engine uring|epoll] JOB...
The receipt lands in docs/cfgfix2/receipts/PHASE.json; the job outputs named by
--keep are copied next to it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(32, 48)), 'cfgfix2 CPU boundary'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('phase')
    p.add_argument('jobs', nargs='+')
    p.add_argument('--binary', required=True)
    p.add_argument('--tier', default='quick', choices=['quick', 'full'])
    p.add_argument('--pool', default='a', choices=['a', 'b'],
                   help='a: server 32-39, load 40-47, ports 21800-21849; b: the mirror, 21850-21899')
    p.add_argument('--engine', choices=['uring', 'epoll'])
    p.add_argument('--keep', action='append', default=[],
                   help='job output file glob to archive (relative to the job directory)')
    p.add_argument('--env', action='append', default=[], help='extra NAME=VALUE for the gate')
    a = p.parse_args()
    binary = Path(a.binary).resolve()
    out = ROOT / 'docs/cfgfix2/receipts'
    out.mkdir(parents=True, exist_ok=True)
    logdir = ROOT / 'build/cfgfix2/gate-logs'
    logdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LC_ALL='C', GATE_ONLY_JOBS=' '.join(a.jobs), GATE_PROOF_NO_RATES='1',
               GATE_DIFFER_ORACLE_BIN=str(Path('/home/user/Projects/redis/src/redis-server')))
    if a.engine:
        env['GATE_NET_IO'] = a.engine
        env['GATE_PROOF_NET_IO'] = a.engine
    for item in a.env:
        name, value = item.split('=', 1)
        env[name] = value
    server, load, ports = (('32-39', '40-47', '21800-21849') if a.pool == 'a' else
                           ('40-47', '32-39', '21850-21899'))
    command = ['taskset', '-c', '32-47', 'tests/gate.sh', a.tier, '--server-cores', server,
               '--load-cores', load, '--load-smt', '', '--ports', ports,
               '--candidate-binary', str(binary)]
    before = sha(binary)
    log = logdir / (a.phase + '.log')
    started = time.time()
    with log.open('w') as handle:
        rc = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT).returncode
    finished = time.time()
    assert sha(binary) == before, 'candidate binary changed during the run'
    text = log.read_text(errors='replace')
    run = re.search(r'artifacts: (\S+)', text)
    run_dir = Path(run.group(1)) if run else None
    ledger = re.search(r'ledger: (\S+)', text)
    rows = []
    if ledger and Path(ledger.group(1)).exists():
        for line in Path(ledger.group(1)).read_text().splitlines():
            parts = line.split('\t')
            if len(parts) >= 3 and parts[0] in ('ok', 'FAIL'):
                rows.append(dict(status=parts[0], seconds=float(parts[1]), label=parts[2]))
    record = dict(phase=a.phase, command=command,
                  environment={k: env[k] for k in ('GATE_ONLY_JOBS', 'GATE_PROOF_NO_RATES',
                                                    'GATE_NET_IO', 'GATE_PROOF_NET_IO') if k in env},
                  binary=str(binary), binary_sha256=before, returncode=rc, started=started,
                  finished=finished, run=str(run_dir) if run_dir else None, log=str(log.relative_to(ROOT)),
                  log_sha256=sha(log), rows=rows,
                  summary=dict(ok=sum(r['status'] == 'ok' for r in rows),
                               fail=sum(r['status'] == 'FAIL' for r in rows)))
    if run_dir and run_dir.exists():
        kept = out / a.phase
        for job in a.jobs:
            jobdir = run_dir / 'jobs' / job
            if not jobdir.exists():
                continue
            for pattern in a.keep + ['proof.log', 'proof/results.json', 'proof/*-observations.json']:
                for source in jobdir.glob(pattern):
                    if source.is_file() and source.stat().st_size < 4 << 20:
                        target = kept / job / source.relative_to(jobdir)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
    (out / (a.phase + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(dict(phase=a.phase, rc=rc, **record['summary'])))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
