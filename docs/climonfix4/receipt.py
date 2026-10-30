#!/usr/bin/env python3
"""Record a completed partial-gate campaign without treating a failed row as green."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('name')
parser.add_argument('log', type=Path)
parser.add_argument('--exit', type=int, required=True)
parser.add_argument('--engine', choices=('uring', 'epoll'))
parser.add_argument('--source-commit', default='c369ccc41')
args = parser.parse_args()
log = args.log.read_text()
run = Path(re.search(r'artifacts: (\S+)', log)[1])
summary = re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;[^\n]*', log)
assert summary, 'Campaign is incomplete'
assert args.exit == (1 if int(summary[2]) else 0)
jobs = re.search(r'PARTIAL jobs \(including prerequisites\): ([^\n]+)', log)[1].split()
for name in jobs:
    assert (run / 'jobs' / name / 'done').exists(), name
binary = ROOT / 'build/climonfix4/tomokv-POST'
server, load, ports = ('24-31', '16-23', '20230-20239') if args.engine else ('16-23', '24-31', '20200-20209')
env = dict(REDIS74_ROOT='/home/user/Projects/redis', GATE_ONLY_JOBS=' '.join(jobs))
if args.engine:
    env.update(GATE_NET_IO=args.engine, GATE_DIFFER_NET_IO=args.engine,
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server')
row = dict(name=args.name, exit=args.exit, artifacts=str(run),
           replay_argv=['taskset', '-c', '16-31', 'env'] + [k + '=' + v for k, v in env.items()] +
                ['bash', 'tests/gate.sh', 'full' if args.engine else 'quick',
                 '--server-cores', server, '--load-cores', load, '--server-smt', '', '--load-smt', '',
                 '--ports', ports, '--candidate-binary', str(binary)],
           env=env, source_commit=args.source_commit,
           binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
           gate_sha256=hashlib.sha256((ROOT / 'tests/gate.sh').read_bytes()).hexdigest(),
           manifest_sha256=hashlib.sha256((ROOT / 'tests/redis_tcl_passing.json').read_bytes()).hexdigest(),
           log=str(args.log), log_sha256=hashlib.sha256(args.log.read_bytes()).hexdigest(),
           summary=summary[0], passed=int(summary[1]), failed=int(summary[2]), jobs=jobs)
assert not subprocess.check_output(['git', 'diff', args.source_commit, '--', 'src'], cwd=ROOT)
(ROOT / 'docs/climonfix4/jobs' / (args.name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
print(row['summary'])
