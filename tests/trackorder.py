#!/usr/bin/env python3
"""Flush invalidation wire order: exact frames, independent connections, Redis 7.4 oracle.

No rate or timing verdicts. Each case uses fresh tracking state; every missing,
extra or reordered frame fails. Receipts contain the complete tested byte streams.
"""
import argparse
import contextlib
import itertools
import json
import os
from pathlib import Path
import select
import subprocess

from _lib import Conn, encode, info, wait_ready
from _gate_process import server, stop_process
from trackfix import raw_frame


def equal(actual, expected):
    assert actual == expected, (actual, expected)


def receive(c, count):
    frames = []
    for _ in range(count):
        assert select.select([c.sock], [], [], 5)[0], ('missing frame', frames)
        frames.append(raw_frame(c))
    while select.select([c.sock], [], [], .002)[0]:
        frames.append(raw_frame(c))
    return [f.hex() for f in frames]


def exercise(port, case):
    protocol, option, command, sync, pipeline, own, noloop = case
    peers = []

    def connect():
        c = Conn('127.0.0.1', port, timeout=5, buffering=0)
        peers.append(c)
        return c

    try:
        writer, tracker, other = connect(), connect(), connect()
        # Seed before tracking: BCAST must have no pending key invalidations.
        equal(writer.cmd('SET', 'trackorder:key', 'value'), b'OK')
        listeners = []
        for c in (tracker, other):
            if protocol == 3:
                c.cmd('HELLO', 3)
                listener, redirect = c, []
            else:
                listener = connect()
                redirect = ['REDIRECT', listener.cmd('CLIENT', 'ID')]
                equal(listener.cmd('SUBSCRIBE', '__redis__:invalidate'),
                      [b'subscribe', b'__redis__:invalidate', 1])
            flags = [] if option == 'default' else [option.split('-')[0]]
            if noloop:
                flags += ['NOLOOP']
            equal(c.cmd('CLIENT', 'TRACKING', 'ON', *redirect, *flags), b'OK')
            if option == 'OPTIN':
                equal(c.cmd('CLIENT', 'CACHING', 'YES'), b'OK')
            if option == 'OPTOUT-off':
                equal(c.cmd('CLIENT', 'CACHING', 'NO'), b'OK')
            equal(c.cmd('GET', 'trackorder:key'), b'value')
            listeners.append(listener)
        flusher = tracker if own else writer
        commands = [('ECHO', 'before'), (command, sync), ('ECHO', 'after')] if pipeline else [(command, sync)]
        wire = b''.join(encode(*args) for args in commands)
        flusher.raw(wire)
        same_stream = protocol == 3 and own
        streams = {'flusher': receive(flusher, len(commands) + int(same_stream))}
        for name, listener in zip(('tracker', 'other'), listeners):
            if listener is not flusher:
                streams[name] = receive(listener, 1)
        # A command after the observed invalidation fences unexpected duplicates.
        for name, listener in zip(('tracker', 'other'), listeners):
            listener.raw(encode('PING'))
            streams[name + '_fence'] = receive(listener, 1)
        return dict(request_hex=wire.hex(), streams=streams)
    finally:
        for c in peers:
            c.close()


@contextlib.contextmanager
def oracle(binary, cores, port, output):
    output.mkdir(parents=True)
    assert not subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{port}']).strip()
    argv = ['taskset', '-c', cores, str(binary), '--bind', '127.0.0.1', '--port', str(port),
            '--save', '', '--appendonly', 'no', '--dir', str(output.resolve())]
    (output / 'argv.json').write_text(json.dumps(argv))
    with (output / 'server.log').open('w') as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        try:
            c = wait_ready('127.0.0.1', port, process=proc)
            version = info(c, 'server')['redis_version']
            assert version.startswith('7.4.'), version
            c.close()
            yield
        finally:
            forced = stop_process(proc)
            (output / 'exit.json').write_text(json.dumps(dict(rc=proc.returncode, forced=forced)))
            assert proc.returncode == 0 and not forced


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--oracle', type=Path, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    args.output.mkdir(parents=True, exist_ok=True)
    cases = list(itertools.product((3, 2),
        ('default', 'BCAST', 'OPTIN', 'OPTIN-off', 'OPTOUT', 'OPTOUT-off'),
        ('FLUSHALL', 'FLUSHDB'), ('SYNC', 'ASYNC'), (False, True), (True, False), (False, True)))
    expected = []
    with oracle(args.oracle, args.cores, args.port + 1, args.output / 'oracle'):
        for case in cases:
            expected.append(dict(case=case, **exercise(args.port + 1, case)))
    (args.output / 'oracle.json').write_text(json.dumps(expected, indent=2) + '\n')
    failures = 0
    summary = []
    for databases, mode, engine, atomic in itertools.product((1, 16), ('1s', '2s'), ('epoll', 'uring'), (0, 1)):
        for read_local in (0, 1) if mode == '1s' else (0,):
            label = f'db{databases}-{mode}-{engine}-a{atomic}-rl{read_local}'
            dest = args.output / label
            flags = ['--shards', 16, '--thread-mode', mode, '--net-io', engine,
                     '--atomic', atomic, '--read-local', read_local,
                     '--key-lb', 0, '--client-lb', 0, '--flip-auto', 0]
            if mode == '2s':
                flags += ['--ratio', args.ratio]
            rows = []
            with server(args.binary, args.cores, args.port, dest, flags, databases=databases) as (admin, _):
                observed = info(admin, 'server')
                for key, wanted in dict(thread_mode=mode, net_io=engine, atomic=str(atomic),
                                        read_local=str(read_local), shards='16').items():
                    equal(observed[key], wanted)
                for baseline in expected:
                    case = baseline['case']
                    row = dict(case=case)
                    try:
                        row.update(exercise(args.port, case))
                        equal(row['streams'], baseline['streams'])
                        row['pass'] = True
                    except Exception as exc:
                        row.update(error=repr(exc), **{'pass': False})
                        failures += 1
                    rows.append(row)
                (dest / 'frames.json').write_text(json.dumps(rows, indent=2) + '\n')
            summary.append(dict(leg=label, passed=sum(r['pass'] for r in rows), failed=sum(not r['pass'] for r in rows)))
            print(json.dumps(summary[-1]), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
