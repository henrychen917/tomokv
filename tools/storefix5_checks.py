#!/usr/bin/env python3
"""Finite correctness/footprint checks. No offered-load or throughput measurement."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn
import storefix5


def run(a):
    assert os.sched_getaffinity(0) <= set(range(16, 24))
    assert 21600 <= a.port <= 21699
    binary = str(a.binary.resolve())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'build/storefix5') as directory:
        args = [binary, '--bind', '127.0.0.1', '--port', str(a.port), '--save', '',
                '--appendonly', 'no', '--enable-debug-command', 'yes', '--dir', directory]
        if not a.redis:
            args += ['--thread-mode', a.mode, '--shards', '16',
                     '--databases', str(a.databases), '--net-io', a.engine]
            if a.mode == '2s': args += ['--ratio', '6:2']
        if a.maxmemory:
            args += ['--maxmemory', str(a.maxmemory), '--maxmemory-policy', a.policy]
        result = dict(binary=binary, sha256=hashlib.file_digest(open(binary, 'rb'), 'sha256').hexdigest(),
                      argv=args, affinity=sorted(os.sched_getaffinity(0)), locale='C', cases={})
        with a.output.with_suffix('.server.log').open('w') as log:
            proc = subprocess.Popen(args, cwd=directory, env=dict(os.environ, LC_ALL='C'),
                                    stdout=log, stderr=subprocess.STDOUT)
            c = None
            try:
                for _ in range(300):
                    if proc.poll() is not None:
                        raise RuntimeError('boot failed: ' + str(a.output.with_suffix('.server.log')))
                    try:
                        c = Conn('127.0.0.1', a.port, timeout=120)
                        assert c.cmd('PING') == b'PONG'
                        break
                    except OSError:
                        time.sleep(.1)
                assert c is not None, 'not ready'
                for name in a.cases.split(','):
                    try:
                        kw = dict(strict=False) if a.redis and name == 'randomkey' else {}
                        if name == 'memory_limit':
                            kw = dict(limit=a.maxmemory, value_size=a.value_size, policy=a.policy)
                        result['cases'][name] = dict(result=getattr(storefix5, name)(c, **kw), passed=True)
                    except AssertionError as exc:
                        result['cases'][name] = dict(passed=False, error=str(exc))
            finally:
                if c: c.close()
                proc.terminate()
                try: proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(); result['forced_stop'] = True
                result['exit'] = proc.returncode
                a.output.write_text(json.dumps(result, indent=2) + '\n')
        assert result['exit'] == 0 and not result.get('forced_stop'), result
        assert all(row['passed'] for row in result['cases'].values()), result['cases']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), default='2s')
    p.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--databases', type=int, default=16)
    p.add_argument('--port', type=int, default=21600)
    p.add_argument('--redis', action='store_true')
    p.add_argument('--maxmemory', type=int, default=0)
    p.add_argument('--value-size', type=int, default=100)
    p.add_argument('--policy', choices=('allkeys-lru', 'noeviction'), default='allkeys-lru')
    p.add_argument('--cases', default='randomkey,append,idle')
    p.add_argument('--output', type=Path, required=True)
    run(p.parse_args())
