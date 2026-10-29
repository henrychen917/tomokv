#!/usr/bin/env python3
"""Run whole correctness jobs through the gate's own partial-job interface."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/climonfix5'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    os.sched_setaffinity(0, set(range(16, 32)))
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('jobs', nargs='+')
    parser.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--tier', choices=('quick', 'full'), default='quick')
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv-climonfix5-POST')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--ports', default='20200-20209')
    args = parser.parse_args()
    jobs = DOC / 'jobs';jobs.mkdir(exist_ok=True)
    binary = args.binary.resolve();digest = sha(binary)
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    source_diff_sha256 = hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--', 'src'], cwd=ROOT)).hexdigest()
    env_delta = dict(LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        GATE_ONLY_JOBS=' '.join(args.jobs), GATE_NET_IO=args.engine, GATE_DIFFER_NET_IO=args.engine,
        GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server')
    if args.manifest: env_delta['GATE_TCL_MANIFEST'] = str(args.manifest.resolve())
    command = ['bash', 'tests/gate.sh', args.tier, '--server-cores', '16-23',
               '--load-cores', '24-31', '--server-smt', '', '--load-smt', '',
               '--ports', args.ports, '--candidate-binary', str(binary)]
    log = jobs / (args.name + '.log')
    with log.open('w') as stream:
        rc = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **env_delta),
                            stdout=stream, stderr=subprocess.STDOUT).returncode
    text = log.read_text()
    match = re.search(r'artifacts: (\S+)', text)
    record = dict(name=args.name, exit=rc, command=command, env=env_delta,
        source_commit=source_commit, source_diff_sha256=source_diff_sha256,
        binary=str(binary), binary_sha256=digest, binary_unchanged=sha(binary)==digest,
        gate_sha256=sha(ROOT/'tests/gate.sh'), log=str(log.relative_to(ROOT)), log_sha256=sha(log))
    if match:
        run = Path(match[1]);record['artifacts'] = str(run)
        ledger = run/'ledger.partial'
        if ledger.exists():
            record['rows'] = [dict(zip(('verdict', 'seconds', 'label'), s.split('\t', 2))) for s in ledger.read_text().splitlines()]
            record['passed'] = sum(r['verdict']=='ok' for r in record['rows'])
            record['failed'] = sum(r['verdict']=='FAIL' for r in record['rows'])
    (jobs/(args.name+'.json')).write_text(json.dumps(record, indent=2)+'\n')
    print(args.name, rc, record.get('passed'), record.get('failed'), flush=True)
    assert record['binary_unchanged'], 'candidate changed during the gate campaign'
    raise SystemExit(rc)

if __name__ == '__main__':
    main()
