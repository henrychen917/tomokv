#!/usr/bin/env python3
"""Classify the supplementary fused txn_nx failure without changing its check.

Reuse the gate's exact contender and conservation assertions on fresh servers.
Redis uses fixed distinct keys because it has no DEBUG SHARDS command. This is
a diagnostic, not a new gate row or a replacement for the failed gate receipt.
Pass --databases 1 --read-local 0 for that gate row's exact boot geometry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import snapfix as s
import txn_nx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default='/home/user/Projects/redis/src/redis-server')
    p.add_argument('--redis', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--rounds', type=int, default=131072)
    p.add_argument('--databases', type=int, choices=[1, 16], default=16)
    p.add_argument('--read-local', type=int, choices=[0, 1], default=1)
    args = p.parse_args()
    assert args.rounds > 0
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    args.port, args.cores, args.stall = 20100, '0-7', 30
    args.host = '127.0.0.1'
    if args.redis:
        txn_nx.geometry = lambda _: (['snapfix2:nx:a', 'snapfix2:nx:b', 'snapfix2:nx:dst'], None)
    with s.Boot(args, args.output, '1s', 'uring', 1, args.redis) as boot:
        args.port = boot.port
        if not args.redis:
            for name, value in [('databases', args.databases), ('read-local', args.read_local)]:
                assert boot.c.must('CONFIG', 'GET', name)[1] == str(value).encode()
        result = txn_nx.race(args, boot.c, transactional=False)
        with Path(args.oracle if args.redis else args.binary).open('rb') as f:
            result['binary_sha256'] = hashlib.file_digest(f, 'sha256').hexdigest()
        result['server_argv'] = boot.argv
        (args.output / 'result.json').write_text(json.dumps(result, default=repr, indent=2) + '\n')
    return int(bool(result['failures'] or result['errors'] or result['threads_alive'] or
                    result['completed'] != result['rounds']))


if __name__ == '__main__':
    raise SystemExit(main())
