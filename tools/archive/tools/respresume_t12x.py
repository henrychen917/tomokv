#!/usr/bin/env python3
"""T12 at nanosecond CPU resolution, repeated, for the "within 3x of Redis" bound.

The audit's T12 reads utime+stime (10 ms ticks), which cannot resolve Redis's
per-frame cost. This driver sends the same frames the same way (one write, and
2 KiB chunks with 0.5 ms gaps) and sums run time over every server thread from
/proc/PID/task/*/schedstat. An idle window of the trickle's own wall time is
measured right after each trickle and reported (not subtracted). Servers: tomo
(the T12 boot: default geometry, CPUs 64-71) and Redis 7.4.10 (CPU 72). Driver
CPUs 73-79. Correctness bound only; not a throughput claim.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import time

REDIS = '/home/user/Projects/redis74/src/redis-server'


def cpu_ns(pid):
    total = 0
    for task in Path(f'/proc/{pid}/task').iterdir():
        try:
            total += int((task / 'schedstat').read_text().split()[0])
        except (FileNotFoundError, ProcessLookupError):
            pass
    return total


def frame(n):
    return b'*%d\r\n$4\r\nPING\r\n' % n + b'$1\r\na\r\n' * (n - 1)


def send(port, payload, chunk, gap):
    s = socket.create_connection(('127.0.0.1', port), timeout=120)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    t0 = time.perf_counter()
    if chunk:
        for i in range(0, len(payload), chunk):
            s.sendall(payload[i:i + chunk])
            time.sleep(gap)
    else:
        s.sendall(payload)
    reply = b''
    while not reply.endswith(b'\r\n'):
        data = s.recv(256)
        assert data, 'server closed'
        reply += data
    wall = time.perf_counter() - t0
    s.close()
    assert reply == b"-ERR wrong number of arguments for 'ping' command\r\n", reply
    return wall


def boot(kind, binary, port, workdir):
    assert 25400 <= port <= 25449
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0, 'port busy'
    cpus = '64-71' if kind != 'redis' else '72'
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    argv = ['taskset', '-c', cpus, str(Path(binary).resolve()), '--bind', '127.0.0.1',
            '--port', str(port), '--save', '', '--appendonly', 'no', '--dir', str(workdir)]
    log = (workdir / 'server.log').open('wb')
    p = subprocess.Popen(argv, cwd=workdir, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 30
    while time.time() < deadline:
        assert p.poll() is None, (workdir / 'server.log').read_text()[-2000:]
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2) as s:
                s.sendall(b'*1\r\n$4\r\nPING\r\n')
                if s.recv(64).startswith(b'+PONG'):
                    break
        except OSError:
            pass
        time.sleep(.05)
    else:
        raise RuntimeError('boot failed')
    return p, argv


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tomo', action='append', default=[], help='label=binary')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--port', type=int, default=25430)
    ap.add_argument('--repeats', type=int, default=5)
    args = ap.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(73, 80)), 'pin the driver to 73-79'
    args.output.mkdir(parents=True, exist_ok=True)
    servers = [('redis', REDIS)] + [tuple(item.split('=', 1)) for item in args.tomo]
    rows = []
    for label, binary in servers:
        p, argv = boot('redis' if label == 'redis' else 'tomo', binary, args.port, args.output / label)
        try:
            for n in (50_000, 100_000, 200_000):
                payload = frame(n)
                one, trickle, idle, walls = [], [], [], []
                for _ in range(args.repeats):
                    c0 = cpu_ns(p.pid)
                    send(args.port, payload, 0, 0)
                    c1 = cpu_ns(p.pid)
                    wall = send(args.port, payload, 2048, .0005)
                    c2 = cpu_ns(p.pid)
                    time.sleep(wall)
                    c3 = cpu_ns(p.pid)
                    one.append((c1 - c0) / 1e9)
                    trickle.append((c2 - c1) / 1e9)
                    idle.append((c3 - c2) / 1e9)
                    walls.append(wall)
                row = dict(server=label, binary=binary, argv=argv, n=n, bytes=len(payload),
                           one_write_cpu_s=one, trickled_cpu_s=trickle, idle_window_cpu_s=idle,
                           trickle_wall_s=walls, median_one_write=statistics.median(one),
                           median_trickled=statistics.median(trickle),
                           median_idle_window=statistics.median(idle))
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != 'argv'}), flush=True)
        finally:
            p.terminate()
            p.wait(timeout=20)
    redis = {r['n']: r['median_trickled'] for r in rows if r['server'] == 'redis'}
    for r in rows:
        r['ratio_to_redis'] = r['median_trickled'] / redis[r['n']] if redis[r['n']] else None
    (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    for r in rows:
        print(f"{r['server']:6} N={r['n']:7} trickled median={r['median_trickled']*1e3:8.2f} ms "
              f"one-write median={r['median_one_write']*1e3:7.2f} ms idle-window median="
              f"{r['median_idle_window']*1e3:6.2f} ms ratio_to_redis={r['ratio_to_redis']:.2f}")


if __name__ == '__main__':
    main()
