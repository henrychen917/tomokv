#!/usr/bin/env python3
"""PFMESSAG.1: one open-loop MSET connection at a fixed rate, never saturation.

An idle RESP3 tracking connection supplies OFF, unmatched BCAST, or default
tracking with one preread of the existing keys per cell (before timed traffic).
The sender keeps its clock independent of replies; latency includes dispatch lag.
Raw samples, lag, CPU occupancy and load are preserved for every boot/cell.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

from clientfix import Conn, Push, enc, server


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)]


def load_snapshot():
    return dict(loadavg=Path('/proc/loadavg').read_text().strip(),
                pressure=Path('/proc/pressure/cpu').read_text().strip(),
                cpus={row.split()[0]: list(map(int, row.split()[1:]))
                      for row in Path('/proc/stat').read_text().splitlines()
                      if row.split()[0] in {f'cpu{i}' for i in range(112, 128)}})


def cell(writer, observer, width, tracking, samples, rate):
    keys = [f'pf:{i:04d}' for i in range(width)]
    command = enc(['MSET', *[arg for key in keys for arg in (key, 'v')]])
    assert observer.cmd("CLIENT", "TRACKING", "OFF") == b"OK"
    writer.s.settimeout(30)
    observer.cmd('HELLO', 3)
    # Existing keys and a warmed command path, all outside the timed interval.
    for _ in range(20):
        writer.s.sendall(command)
        assert writer.read() == b'OK'
    if tracking == 'bcast':
        assert observer.cmd('CLIENT', 'TRACKING', 'ON', 'BCAST', 'PREFIX', 'never:') == b'OK'
    elif tracking == 'default':
        assert observer.cmd('CLIENT', 'TRACKING', 'ON') == b'OK'
        assert observer.cmd('MGET', *keys) == [b'v'] * width
    before = load_snapshot()
    origin = time.perf_counter_ns() + 50_000_000
    period = round(1e9 / rate)
    sent = [0] * samples
    received = []
    errors = []

    def send():
        try:
            for index in range(samples):
                deadline = origin + index * period
                remaining = deadline - time.perf_counter_ns()
                if remaining > 0:
                    time.sleep(remaining / 1e9)
                sent[index] = time.perf_counter_ns()
                writer.s.sendall(command)
        except BaseException as exc:
            errors.append(repr(exc))

    sender = threading.Thread(target=send)
    sender.start()
    try:
        for _ in range(samples):
            assert writer.read() == b'OK'
            received.append(time.perf_counter_ns())
    finally:
        sender.join(timeout=30)
    assert not sender.is_alive() and not errors, errors
    after = load_snapshot()
    pushes = observer.drain(.05)
    invalidated = {key for frame in pushes if isinstance(frame, Push)
                   and frame[0] == b'invalidate' and frame[1] is not None
                   for key in frame[1]}
    if tracking == 'default':
        assert invalidated == {key.encode() for key in keys}, len(invalidated)
    else:
        assert not pushes, pushes
    latency = [(end - origin - i * period) / 1000 for i, end in enumerate(received)]
    service = [(end - start) / 1000 for end, start in zip(received, sent)]
    lag = [(start - origin - i * period) / 1000 for i, start in enumerate(sent)]
    return dict(width=width, tracking=tracking, samples=samples, rate=rate,
                p50_us=percentile(latency, .5), p99_us=percentile(latency, .99),
                send_to_reply_p50_us=percentile(service, .5),
                send_to_reply_p99_us=percentile(service, .99),
                lag_p99_us=percentile(lag, .99),
                below_offered_period=percentile(latency, .99) < period / 1000,
                latency_us=latency, service_us=service, lag_us=lag,
                load_before=before, load_after=after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre', required=True)
    parser.add_argument('--post', required=True)
    parser.add_argument('--redis', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--oracle-cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--boots', type=int, default=3)
    parser.add_argument('--samples', type=int, default=1000)
    parser.add_argument('--rate', type=float, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.boots >= 3 and args.samples >= 1000 and args.rate > 0
    assert not args.output.exists(), 'never overwrite a measurement receipt'
    hashes = {arm: hashlib.sha256(Path(getattr(args, arm)).read_bytes()).hexdigest()
              for arm in ('pre', 'post', 'redis')}
    arms = [('pre', '1s'), ('post', '1s'), ('redis', 'oracle'), ('post', '2s'), ('pre', '2s')]
    shapes = [(width, tracking) for width in (1, 32, 256, 1024)
              for tracking in ('off', 'bcast', 'default')]
    with args.output.open('x') as output:
        for boot in range(args.boots):
            for arm, mode in arms if boot % 2 == 0 else reversed(arms):
                extra_flags = ['--slowlog-log-slower-than', '-1', '--latency-monitor-threshold', '0']
                if arm != 'redis':
                    extra_flags += ['--reorder', '0', '--key-lb', '0', '--client-lb', '0']
                config = argparse.Namespace(binary=getattr(args, arm), port=args.port,
                                            cores=args.oracle_cores if arm == 'redis' else args.cores,
                                            ratio=args.ratio, mode=mode, oracle=arm == 'redis',
                                            extra_flags=extra_flags)
                with server(config) as port, Conn(args.port) as writer, Conn(args.port) as observer:
                    # Keep connection ownership fixed across every OFF/ON cell in this boot.
                    ids = dict(writer=writer.cmd('CLIENT', 'ID'), observer=observer.cmd('CLIENT', 'ID'))
                    # Rotate cell order as well as the interleaved PRE/POST boot order.
                    order = shapes[boot:] + shapes[:boot]
                    for width, tracking in order:
                        row = cell(writer, observer, width, tracking, args.samples, args.rate)
                        row['client_ids'] = ids
                        row.update(arm=arm, mode=mode, boot=boot, sha256=hashes[arm],
                                   client_affinity=sorted(os.sched_getaffinity(0)),
                                   server_cores=config.cores, ratio=args.ratio,
                                   atomic=0, read_local=0, extra_flags=extra_flags)
                        output.write(json.dumps(row) + '\n')
                        output.flush()
                        print(json.dumps({k: row[k] for k in ('arm', 'mode', 'boot', 'width',
                              'tracking', 'p50_us', 'p99_us', 'below_offered_period')}), flush=True)


if __name__ == '__main__':
    main()
