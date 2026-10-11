#!/usr/bin/env python3
"""Fixed-command mkfix count runs. No rate or latency measurement or claims.

Runs only on CPUs 32-47 and ports 25500-25599. WB totals come from a clean
shutdown of the unmodified arm. Optional scratch LD_PRELOAD counts cover only
the measured commands on warmed, persistent connections. Never a gate row.
"""
import argparse
import asyncio
import hashlib
import json
import mmap
import multiprocessing as mp
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn, encode


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def info(c):
    raw = c.cmd('INFO', 'all').decode()
    return dict(line.split(':', 1) for line in raw.splitlines()
                if ':' in line and not line.startswith('#'))


def calls(stats, command):
    raw = stats.get('cmdstat_' + command.lower(), '')
    return int(dict(x.split('=', 1) for x in raw.split(',') if '=' in x).get('calls', 0))


def worker(cpu, port, frame, reply, pipeline, connections, commands, barrier):
    os.sched_setaffinity(0, {cpu})

    async def run():
        pairs = [await asyncio.open_connection('127.0.0.1', port)
                 for _ in range(connections)]
        for _, w in pairs:
            w.get_extra_info('socket').setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        async def traffic(pair, count):
            reader, writer = pair
            for start in range(0, count, pipeline):
                n = min(pipeline, count - start)
                writer.write(frame * n)
                await writer.drain()
                actual = await asyncio.wait_for(reader.readexactly(len(reply) * n), 60)
                require(actual == reply * n, 'wire reply differs from the expected complete reply')

        await asyncio.gather(*(traffic(pair, 128) for pair in pairs))
        barrier.wait(90)  # warmed, no command in flight
        barrier.wait(90)  # parent sampled INFO and enabled optional allocation counts
        await asyncio.gather(*(traffic(pair, commands) for pair in pairs))
        barrier.wait(90)  # every expected reply consumed
        barrier.wait(90)  # parent disabled counts and sampled INFO
        for _, w in pairs:
            w.close()
        await asyncio.gather(*(w.wait_closed() for _, w in pairs))

    asyncio.run(run())


def case(args, mode, command, atomic, pipeline, keys, rep):
    label = f'{mode}-{command.lower()}-a{atomic}-p{pipeline}-k{keys}-r{rep}'
    out = args.output / label
    out.mkdir(parents=True, exist_ok=False)
    require(25500 <= args.port <= 25599, 'port outside lane allocation')
    with socket.socket() as guard:
        guard.bind(('127.0.0.1', args.port))
    names = [f'mkfix:{i:06d}'.encode() for i in range(keys)]
    value = b'x' * args.value_size
    frame = encode(command, *([x for k in names for x in (k, value)]
                              if command == 'MSET' else names))
    bulk = b'$%d\r\n%s\r\n' % (len(value), value)
    reply = b'+OK\r\n' if command == 'MSET' else (
        b'*%d\r\n' % keys + bulk * keys if command == 'MGET' else bulk)
    env = os.environ.copy()
    shared = None
    if args.shim:
        path = out / 'counts.bin'
        path.write_bytes(bytes(4096))
        with path.open('r+b') as handle:
            shared = mmap.mmap(handle.fileno(), 4096)
        env.update(LD_PRELOAD=str(args.shim), MKFIX_COUNTS_FILE=str(path))
    argv = ['taskset', '-c', '32-39', str(args.binary), '--port', str(args.port),
            '--bind', '127.0.0.1', '--thread-mode', mode,
            '--shards', '16', '--read-local', '0', '--atomic', str(atomic),
            '--save', '', '--dir', str(out), '--wb-policy', str(args.policy)]
    if mode == '2s':
        argv += ['--ratio', '6:2']
    children = []
    connection = None
    server = None
    barrier = mp.Barrier(9)
    try:
        with (out / 'server.log').open('w') as log:
            server = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        for _ in range(300):
            require(server.poll() is None, f'{label}: server exited; see {out}/server.log')
            try:
                connection = Conn('127.0.0.1', args.port, timeout=10)
                require(connection.cmd('PING') == b'PONG', 'readiness reply')
                break
            except OSError:
                time.sleep(.05)
        require(connection is not None, 'server never became ready')
        for key in names:
            require(connection.cmd('SET', key, value) == b'OK', 'population failed')
        for cpu in range(40, 48):
            child = mp.Process(target=worker, args=(cpu, args.port, frame, reply, pipeline,
                               args.connections // 8, args.commands, barrier))
            child.start()
            children.append(child)
        barrier.wait(90)
        before = info(connection)
        if shared:
            struct.pack_into('<Q', shared, 0, 1)
        barrier.wait(90)
        barrier.wait(90)
        if shared:
            struct.pack_into('<Q', shared, 0, 0)
        after = info(connection)
        barrier.wait(90)
        for child in children:
            child.join(30)
            require(child.exitcode == 0, f'worker exited {child.exitcode}')
        measured = calls(after, command) - calls(before, command)
        require(measured == args.commands * args.connections,
                f'cmdstat count {measured} != sent {args.commands * args.connections}')
        connection.close()
        connection = None
        server.send_signal(signal.SIGTERM)
        require(server.wait(30) == 0, 'server failed clean shutdown')
        reports = [json.loads(line.split('shutdown_report ', 1)[1])
                   for line in (out / 'server.log').read_text().splitlines()
                   if line.startswith('shutdown_report ')]
        require(len(reports) == 1, 'missing or ambiguous shutdown report')
        report = reports[0]
        wb = report['wb']
        require(wb['sends_submitted'] > 0 and wb['retired'] >= measured,
                'WB witness is vacuous')
        require(wb['send_errors'] == 0 and wb['peer_aborts'] == 0, 'failed sends')
        result = dict(label=label, mode=mode, command=command, atomic=atomic,
                      pipeline=pipeline, keys=keys, replica=rep, value_size=args.value_size,
                      measured_calls=measured, policy=args.policy, wb=wb,
                      replies_per_send=wb['retired'] / wb['sends_submitted'],
                      argv=argv, binary_sha256=args.binary_sha256,
                      instrumented=bool(args.shim), info_before=before, info_after=after)
        result['fanout_cuts'] = int(after.get('atomic_fanout_cuts', 0)) - int(before.get('atomic_fanout_cuts', 0))
        result['fanout_cuts_per_call'] = result['fanout_cuts'] / measured
        if shared:
            totals = struct.unpack_from('<512Q', shared)
            names = ['malloc', 'calloc', 'realloc', 'posix_memalign', 'aligned_alloc', 'mallocx', 'rallocx']
            labels = ['calls', 'requested_bytes', 'n192', 'n384', 'n768', 'n256', 'n512', 'n1024', 'n1536', 'n16384']
            result['allocations'] = {name: dict(zip(labels, totals[8 + i*16:8 + i*16 + 10]))
                                     for i, name in enumerate(names)}
            result['allocations_per_call'] = sum(x['calls'] for x in result['allocations'].values()) / measured
            result['sweeps'] = dict(zip(['calls', 'visited', 'removed', 'max_length'], totals[128:132]))
        (out / 'row.json').write_text(json.dumps(result, indent=2) + '\n')
        with (args.output / 'rows.jsonl').open('a') as handle:
            handle.write(json.dumps(result) + '\n')
        print(json.dumps({k: result[k] for k in ('label', 'measured_calls', 'replies_per_send',
              'fanout_cuts_per_call', 'allocations_per_call', 'sweeps') if k in result}), flush=True)
    finally:
        try:
            barrier.abort()
        except Exception:
            pass
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(10)
        if connection:
            connection.close()
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if shared:
            shared.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--shim', type=Path)
    p.add_argument('--port', type=int, default=25500)
    p.add_argument('--connections', type=int, default=64)
    p.add_argument('--commands', type=int, default=1024, help='per connection, after 128 warm commands')
    p.add_argument('--replicas', type=int, default=1)
    p.add_argument('--modes', nargs='+', choices=['1s', '2s'], default=['1s', '2s'])
    p.add_argument('--depths', nargs='+', type=int, default=[8, 32, 128])
    p.add_argument('--keys', nargs='+', type=int, default=[8])
    p.add_argument('--commands-list', nargs='+', choices=['GET', 'MGET', 'MSET'], default=['GET', 'MGET', 'MSET'])
    p.add_argument('--atomics', nargs='+', type=int, choices=[0, 1], default=[0, 1])
    p.add_argument('--policy', type=int, choices=[0, 1], default=1)
    p.add_argument('--value-size', type=int, default=64)
    a = p.parse_args()
    require(set(os.sched_getaffinity(0)) <= set(range(32, 48)), 'pin entire command to CPUs 32-47')
    require(a.connections > 0 and a.connections % 8 == 0, 'connections must be a positive multiple of 8')
    a.binary = a.binary.resolve(strict=True)
    a.binary_sha256 = hashlib.sha256(a.binary.read_bytes()).hexdigest()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    if a.shim:
        a.shim = a.shim.resolve(strict=True)
    for mode in a.modes:
        for command in a.commands_list:
            for atomic in ([0] if command == 'GET' else a.atomics):
                for pipeline in a.depths:
                    for keys in ([1] if command == 'GET' else a.keys):
                        for replica in range(a.replicas):
                            case(a, mode, command, atomic, pipeline, keys, replica)


if __name__ == '__main__':
    main()
