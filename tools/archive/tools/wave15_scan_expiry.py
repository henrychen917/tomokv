#!/usr/bin/env python3
"""SCAN's physical expiry of the keys it visits, per arm (owner decision 4, wave15 phase 2).

One fresh boot per arm: N tracked keys PX 3000 (RESP3 CLIENT TRACKING, every key read once),
active expiry off, sleep past the TTL, one complete SCAN COUNT 100000 iteration, then read what
a Redis client can see: DBSIZE, INFO expired_keys and the invalidations that arrived within one
second. Correctness probe only: no rates, no load generator. Writes one JSON row per arm.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/rootcompat_tracking'))
from resp import Conn, info_dict, b2s  # noqa: E402


def probe(binary, port, cores, mode, read_local, n, directory, oracle):
    directory.mkdir(parents=True, exist_ok=True)
    argv = ['taskset', '-c', cores, binary, '--port', str(port), '--bind', '127.0.0.1', '--save', '',
            '--appendonly', 'no', '--dir', str(directory), '--protected-mode', 'no',
            '--enable-debug-command', 'yes']
    if not oracle:
        argv += ['--thread-mode', mode, '--shards', '16', '--databases', '1', '--net-io', 'uring',
                 '--atomic', '0', '--read-local', str(read_local), '--key-lb', '0', '--client-lb', '0']
        if mode == '2s':
            argv += ['--ratio', '6:2']
    proc = subprocess.Popen(argv, stdout=open(directory / 'server.log', 'w'), stderr=subprocess.STDOUT,
                            env=dict(os.environ, LC_ALL='C'))
    try:
        for _ in range(200):
            try:
                socket.create_connection(('127.0.0.1', port), timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        w = Conn(port, timeout=60, name='w')
        t = Conn(port, timeout=60, name='t')
        assert isinstance(t.call('HELLO', '3'), dict)
        assert t.call('CLIENT', 'TRACKING', 'ON') == 'OK'
        assert w.call('DEBUG', 'SET-ACTIVE-EXPIRE', '0') == 'OK'
        keys = ['se:%d' % i for i in range(n)]
        for i in range(0, n, 5000):
            assert all(r == 'OK' for r in w.pipeline([('SET', k, 'v', 'PX', '3000') for k in keys[i:i + 5000]],
                                                      timeout=60))
        for i in range(0, n, 5000):
            assert all(r == b'v' for r in t.pipeline([('GET', k) for k in keys[i:i + 5000]], timeout=60))
        t.poll_pushes(0.05)
        t.pushes.clear()
        time.sleep(3.4)
        before = info_dict(w)
        started, cursor, calls = time.monotonic(), '0', 0
        while True:
            reply = w.call('SCAN', cursor, 'COUNT', '100000', timeout=60)
            calls += 1
            cursor = reply[0].decode() if isinstance(reply[0], bytes) else str(reply[0])
            if cursor == '0':
                break
        seconds = time.monotonic() - started
        dbsize = w.call('DBSIZE')
        expired = int(info_dict(w).get('expired_keys', 0)) - int(before.get('expired_keys', 0))
        t.read_frames_until_quiet(quiet=0.3, max_total=1.0)
        invalidated, flushes = set(), 0
        for _, frame in t.pushes:
            frame = b2s(frame)
            if isinstance(frame, list) and frame and frame[0] == 'invalidate':
                if frame[1] is None:
                    flushes += 1
                else:
                    invalidated.update(frame[1])
        return dict(scan_calls=calls, scan_seconds=round(seconds, 3), dbsize_after_scan=dbsize,
                    expired_keys_after_scan=expired, invalidated_within_1s=len(invalidated),
                    flush_frames_within_1s=flushes)
    finally:
        proc.terminate()
        proc.wait(15)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm', action='append', required=True,
                   help='label=binary[,mode=2s][,read_local=1][,oracle]')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--n', type=int, default=100000)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    a = p.parse_args()
    rows = []
    for spec in a.arm:
        label, _, rest = spec.partition('=')
        fields = rest.split(',')
        options = dict(f.split('=', 1) for f in fields[1:] if '=' in f)
        oracle = 'oracle' in fields[1:]
        mode, read_local = options.get('mode', '2s'), int(options.get('read_local', 1))
        row = dict(arm=label, binary=fields[0], oracle=oracle, mode=None if oracle else mode,
                   read_local=None if oracle else read_local, n=a.n)
        row.update(probe(fields[0], a.port, a.cores, mode, read_local, a.n, a.work / label, oracle))
        print(json.dumps(row), flush=True)
        rows.append(row)
    a.output.write_text(json.dumps(dict(protocol=__doc__.strip(), rows=rows), indent=1) + '\n')


if __name__ == '__main__':
    main()
