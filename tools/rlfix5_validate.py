#!/usr/bin/env python3
"""Run selected gate jobs within the rlfix5 CPU/port allocation and retain receipts."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

import blockfix2_receipts as receipts
from wave13_counts import sha

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/rlfix5/jobs'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tag')
    p.add_argument('--jobs-file', type=Path, required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/rlfix5/POST')
    p.add_argument('--fused', action='store_true')
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(24, 32))
    names = a.jobs_file.read_text().split()
    assert names and not {'flip_saturated', 'efficiency', 'tailgen_build', 'zc'} & set(names)
    DOC.mkdir(parents=True, exist_ok=True)
    assert not (DOC / (a.tag + '.json')).exists(), 'use a fresh attempt tag'
    binary = a.binary.resolve(); digest = sha(binary)
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
        GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',
        GATE_PROOF_NO_RATES='1', GATE_NET_IO=a.engine, GATE_PROOF_NET_IO=a.engine,
        GATE_DIFFER_NET_IO=a.engine, GATE_ONLY_JOBS=' '.join(names),
        GATE_TEST_PORT='21598', GATE_LEDGER=str(DOC / a.tag),
        CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    if a.fused:
        env['GATE_TXN_FUSED'] = '1'
    cmd = ['taskset', '-c', '24-31', 'tests/gate.sh', 'full', '--shared-correctness-cpus',
           '--server-cores', '24-31', '--load-cores', '24-31', '--server-smt', '', '--load-smt', '',
           '--ports', '21500-21599', '--candidate-binary', str(binary)]
    metadata = dict(command=cmd, binary_sha256=digest, engine=a.engine,
        env={k: v for k, v in env.items() if k.startswith('GATE_') or k in ('LC_ALL', 'CXX', 'CC', 'REDIS74_ROOT')})
    (DOC / (a.tag + '-started.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    with (DOC / (a.tag + '.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    runs = re.findall(r'^  artifacts: (.+)$', (DOC / (a.tag + '.log')).read_text(), re.M)
    assert len(runs) == 1, runs
    root = Path(runs[0]); assert root.parent == ROOT / 'build'
    record = receipts.collect(a.tag, root, DOC)
    record.update(metadata, exit_code=result.returncode)
    assert sha(binary) == digest, 'candidate changed during proof'
    (DOC / (a.tag + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(a.tag, 'exit', result.returncode, 'passed', sum(j['passed'] for j in record['jobs']),
          'failed', sum(j['failed'] for j in record['jobs']), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
