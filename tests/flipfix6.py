#!/usr/bin/env python3
"""FLIP/session correctness witness. Fresh 6:2 boot per case and leg; no rates.

The EXEC partner is tests/flipfix5.py's pipelined MULTI INCR INCR EXEC sequence.
Connections cover every IO, so converting an IO must encounter a session. PRE
must refuse at the deadline and the unrelated PING must stall. POST must move
session connections, preserve every reply/value, and keep all gaps below 1 s.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import threading
import time
import traceback

from _lib import RespError, encode
import snapfix as s


def transaction(c, pair, pipeline=True):
    if pipeline:
        c.raw(encode('MULTI') + encode('INCR', pair[0]) + encode('INCR', pair[1]) + encode('EXEC'))
        assert [c.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
        value = c.read()
    else:
        assert c.must('MULTI') == b'OK'
        for key in pair:
            assert c.must('INCR', key) == b'QUEUED'
        value = c.must('EXEC')
    assert isinstance(value, list) and len(value) == 2 and value[0] == value[1], value
    return value[0]


def witness(args, directory, engine, atomic, case):
    result = dict(case=case, flips=[], pings=0, ping_max=0, errors=[], workers=[])
    with s.Boot(args, directory, '2s', engine, atomic, False) as b, contextlib.ExitStack() as stack:
        # Pin the coordinator on IO 0. The other five IOs all contain sessions.
        control = stack.enter_context(contextlib.closing(s.connect(b.port, args.stall, io=0)))
        probe = stack.enter_context(contextlib.closing(s.connect(b.port, args.stall, io=0)))
        db = 7 if args.databases == 16 else 0
        clients = []
        for io in range(6):
            c = stack.enter_context(contextlib.closing(s.connect(b.port, args.stall, io=io)))
            c.must('SELECT', db)
            control.must('SELECT', db)
            pair, owners = s.keys_for(control, f'flipfix6:{io}', False, 2)
            if case == 'p3':
                pair[1] = s.same_owner(control, f'flipfix6:{io}:same', owners[0][1])
                owners[1] = s.placement(control, pair[1])
            control.must('MSET', pair[0], 0, pair[1], 0)
            count = 0
            if case in ('p2', 'watch'):
                assert c.must('WATCH', pair[0]) == b'OK'
                if case == 'p2':
                    assert c.must('UNWATCH') == b'OK'
            else:
                count = transaction(c, pair, pipeline=case != 'p3')
            row = dict(io_before=io, ops=0, execs=count, max_gap=0, owners=owners)
            result['workers'].append(row)
            clients.append((c, pair, row))
        before = s.stats(control)
        stop = threading.Event()
        ready = threading.Event()

        def worker(c, pair, row):
            try:
                while not stop.is_set():
                    begin = time.monotonic()
                    if case in ('exec', 'p3'):
                        value = transaction(c, pair, pipeline=case != 'p3')
                        row['execs'] += 1
                        assert value == row['execs'], (value, row)
                    else:
                        expected = str(row['execs']).encode()
                        assert c.must('GET', pair[0]) == expected
                    row['max_gap'] = max(row['max_gap'], time.monotonic() - begin)
                    row['ops'] += 1
            except Exception:
                result['errors'].append(traceback.format_exc())
                stop.set()

        def ping():
            try:
                while not stop.is_set():
                    begin = time.monotonic()
                    assert probe.must('PING') == b'PONG'
                    result['ping_max'] = max(result['ping_max'], time.monotonic() - begin)
                    result['pings'] += 1
                    ready.set()
            except Exception:
                result['errors'].append(traceback.format_exc())
                stop.set()

        threads = [threading.Thread(target=worker, args=client) for client in clients]
        threads.append(threading.Thread(target=ping))
        for thread in threads:
            thread.start()
        try:
            assert ready.wait(args.stall), 'PING prober did not start'
            s.wait(lambda: all(row['ops'] for row in result['workers']), 'workers never started')
            until = time.monotonic() + args.seconds
            while not stop.is_set() and (not result['flips'] or time.monotonic() < until):
                target = 4 if len(result['flips']) % 2 == 0 else 6
                begin = time.monotonic()
                reply = control.cmd('FLIP', target, 8 - target)
                result['flips'].append(dict(seconds=time.monotonic() - begin,
                    reply=reply.message.decode() if isinstance(reply, RespError) else reply.decode()))
                if isinstance(reply, RespError):
                    break
        finally:
            stop.set()
            for thread in threads:
                thread.join(args.stall)
            assert all(not thread.is_alive() for thread in threads), 'worker failed to stop'
        after = s.stats(control)
        result['sessions_moved'] = after.get('flip_session_clients_transferred', 0) - before.get(
            'flip_session_clients_transferred', 0)
        result['clients_moved'] = after['flip_clients_transferred'] - before['flip_clients_transferred']
        for c, pair, row in clients:
            row['io_after'] = s.io_thread(c)
            assert control.must('MGET', *pair) == [str(row['execs']).encode()] * 2
        (directory / 'witness.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not result['errors'], result['errors']
        if args.expect == 'pre':
            assert len(result['flips']) == 1, result
            refusal = result['flips'][0]
            assert refusal['reply'].startswith('ERR FLIP') and 4.5 <= refusal['seconds'] < args.stall, result
            assert 4.0 <= result['ping_max'] < args.stall, result
            assert all(row['max_gap'] >= 4.0 for row in result['workers']), result
        else:
            assert all(r['reply'] == 'OK' and r['seconds'] < 1 for r in result['flips']), result
            assert len(result['flips']) >= args.min_flips, result
            assert result['sessions_moved'] > 0, ('no session connection moved', result)
            assert result['ping_max'] < 1 and all(row['max_gap'] < 1 for row in result['workers']), result
    assert b.exit == dict(rc=0, forced=False), b.exit
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--cores', default='32-39')
    p.add_argument('--port', type=int, default=20300)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--expect', choices=['pre', 'post'], default='post')
    p.add_argument('--cases', nargs='+', choices=['exec', 'p1', 'p2', 'p3', 'watch'], default=['exec'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--databases', nargs='+', type=int, default=[1, 16])
    p.add_argument('--seconds', type=float, default=6)
    p.add_argument('--stall', type=float, default=10)
    p.add_argument('--min-flips', type=int, default=100)
    args = p.parse_args()
    assert 1024 <= args.port < 32768
    os.environ['LC_ALL'] = 'C'
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for db in args.databases:
        for engine in args.engines:
            for atomic in args.atomics:
                for case in args.cases:
                    leg = f'2s-{engine}-{atomic}-db{db}-{case}'
                    directory = args.output / leg
                    one = argparse.Namespace(**vars(args))
                    one.databases = db
                    record = dict(leg=leg)
                    try:
                        record['result'] = witness(one, directory, engine, atomic, case)
                        record['pass'] = True
                    except Exception:
                        record.update(error=traceback.format_exc(), **{'pass': False})
                    rows.append(record)
                    (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                    print(json.dumps(dict(leg=leg, **{'pass': record['pass']},
                        flips=len(record.get('result', {}).get('flips', [])),
                        ping_max=record.get('result', {}).get('ping_max'),
                        error=record.get('error'))), flush=True)
    return int(any(not row['pass'] for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
