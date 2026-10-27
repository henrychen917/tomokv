#!/usr/bin/env python3
"""Non-gate reproductions for SNAP-STORM-1, XS-SHUT-1 and XS-NOTIFY-1.

Run one cell on PRE, POST or Redis. A reproduced defect returns nonzero and
retains its exception, server exit and argv. Nothing here is a tolerated gate
failure. All scratch files belong to --output inside the caller's worktree.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import traceback

import at412 as a
from _lib import Conn


def shutdown(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    if not oracle:
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 300000)
    with contextlib.ExitStack() as stack:
        clients = [stack.enter_context(contextlib.closing(Conn('127.0.0.1', port))) for _ in range(8)]
        before = a.stats(c)
        for client in clients:
            client.send(*call)
        if not oracle:
            a.wait(lambda: a.stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'],
                   'shutdown diagnostic never opened its script window')
        c.send('SHUTDOWN', 'NOSAVE')
        try:
            reply = c.read()
        except (EOFError, ConnectionError, OSError):
            reply = None
        assert reply is None or reply == b'OK', reply
    # boot() requires a clean exit and records a crash or forced kill as failure.


def notifications(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    c.must('CONFIG', 'SET', 'notify-keyspace-events', 'KEA')
    with contextlib.closing(Conn('127.0.0.1', port)) as sub, \
         contextlib.closing(Conn('127.0.0.1', port)) as track:
        sub.must('SUBSCRIBE', '__keyevent@0__:incrby')
        track.must('HELLO', 3)
        track.must('CLIENT', 'TRACKING', 'ON')
        for key in keys:
            track.must('GET', key)
        assert c.must(*call) == [1, 1]
        a.exact(c, keys, [1, 1])
        events = [e[2] for e in a.drain_messages(sub.sock)]
        track.sock.settimeout(1)
        try:
            invalidations = track.sock.recv(65536)
        except TimeoutError:
            invalidations = b''
        print(json.dumps(dict(events=[k.decode() for k in events],
                              invalidations=invalidations.decode())), flush=True)
        assert sorted(events) == sorted(k.encode() for k in keys), ('XS-NOTIFY-1 events', events)
        assert all(k.encode() in invalidations for k in keys), ('XS-NOTIFY-1 tracking', invalidations)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--defect', choices=['SNAP-STORM-1', 'XS-SHUT-1', 'XS-NOTIFY-1'], required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default='/home/user/Projects/redis74/src/redis-server')
    p.add_argument('--redis', action='store_true')
    p.add_argument('--cores', default='48-55')
    p.add_argument('--port', type=int, default=20280)
    p.add_argument('--mode', choices=['1s', '2s'], default='1s')
    p.add_argument('--engine', choices=['uring', 'epoll'], default='uring')
    p.add_argument('--atomic', type=int, choices=[0, 1], default=0)
    p.add_argument('--attempts', type=int, default=1)
    p.add_argument('--seconds', type=float, default=5)
    p.add_argument('--mix', default='scripts,execs,writers')
    p.add_argument('--pre-control', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for n in range(args.attempts):
        row = dict(defect=args.defect, attempt=n)
        try:
            with a.boot(args, args.output/str(n), args.mode, args.engine, args.atomic, args.redis) as (c, port):
                keys = a.pair(c, 'diagnostic', args.redis)
                call = a.invocation(c, 'EVAL', keys)
                if args.defect == 'SNAP-STORM-1':
                    os.environ['AT412_STORM_MIX'] = args.mix
                    row['value'] = a.storm(c, port, keys, call, args.redis, args.seconds, bgsave=True,
                                          refusals=[0] if args.pre_control else None)
                elif args.defect == 'XS-SHUT-1':
                    shutdown(c, port, keys, call, args.redis)
                else:
                    notifications(c, port, keys, call, args.redis)
            row['pass'] = True
        except Exception:
            row.update(pass_=False, error=traceback.format_exc())
        results.append(row)
        print(json.dumps(row), flush=True)
        (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        if not row.get('pass'):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
