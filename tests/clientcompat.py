#!/usr/bin/env python3
"""Redis 7.4 client compatibility witnesses, run only by gate.sh whole jobs.

The four MULTI shapes are t2_multitrack.py from round4-read/repro-tracking:
foreign write between QUEUED and EXEC, own write first, ordinary control, EXEC
only. Both the early-push and missing-post-EXEC-push assertions are mandatory.
Every case uses fresh connections/keys and records oracle and candidate results.
"""
import argparse
import contextlib
import itertools
import json
import os
from pathlib import Path
import re
import select
import time
import traceback

from _lib import Conn, RespError, encode
from authfix import Run, Server, clean as base_clean

CASES = ('pause', 'disconnect', 'multi-tracking', 'multi-controls', 'enable-race')


def clean(value):
    if isinstance(value, RespError):
        return {'error': str(value)}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return base_clean(value)


class Peer(Conn):
    def __init__(self, port):
        super().__init__('127.0.0.1', port, timeout=4, buffering=0)
        self.pushes = []

    def response(self):
        while True:
            value = self.read()
            if isinstance(value, list) and value and value[0] in (
                    b'invalidate', b'message', b'tracking-redir-broken'):
                self.pushes.append(value)
            else:
                return value

    def cmd(self, *args):
        self.send(*args)
        return self.response()

    def drain(self, wait=.03):
        end = time.monotonic() + wait
        while select.select([self.sock], [], [], max(0, end-time.monotonic()))[0]:
            self.pushes.append(self.read())
            end = min(end, time.monotonic() + .005)
            if time.monotonic() >= end:
                break
        got, self.pushes = self.pushes, []
        return got


def keys(frames):
    result = []
    for frame in frames:
        assert isinstance(frame, list), frame
        if frame[0] == b'invalidate':
            result.extend(frame[1] if frame[1] is not None else [None])
        elif frame[0] == b'message':
            assert frame[1] == b'__redis__:invalidate', frame
            result.extend(frame[2] if frame[2] is not None else [None])
        else:
            raise AssertionError(('unexpected push', frame))
    return result


def probe(case, port, rows, oracle, mode=None):
    with contextlib.ExitStack() as stack:
        def peer(proto=2):
            c = Peer(port)
            stack.callback(c.close)
            if proto == 3:
                assert isinstance(c.cmd('HELLO', 3), list)
            return c

        def check(label, actual, expected):
            rows.append(dict(label=label, actual=clean(actual), expected=clean(expected)))
            assert actual == expected, (label, actual, expected)

        a = peer()
        if case == 'pause':
            # Families exercise WRITE, MAY_REPLICATE, DENYOOM-only, connection,
            # pubsub, script, transaction, administrative, and ordinary reads.
            commands = [
                ('CLIENT', 'ID'), ('CLIENT', 'TRACKINGINFO'), ('CLIENT', 'SETNAME', 'cc'),
                ('CLIENT', 'UNPAUSE'), ('RESET',), ('MONITOR',), ('PING',),
                ('GET', 'cc:pause'), ('SET', 'cc:pause', 'v'), ('INCR', 'cc:n'),
                ('PFCOUNT', 'cc:hll'), ('PUBLISH', 'cc:channel', 'v'),
                ('SPUBLISH', 'cc:channel', 'v'), ('SUBSCRIBE', 'cc:channel'),
                ('CONFIG', 'GET', 'hz'), ('ACL', 'WHOAMI'), ('INFO', 'clients'),
                ('SCRIPT', 'LOAD', 'return 1'), ('EVAL', 'return 1', 0),
                ('EVAL_RO', 'return 1', 0), ('MULTI',), ('XGROUP', 'HELP'),
                ('FUNCTION', 'LIST'), ('FUNCTION', 'LOAD', 'REPLACE',
                    '#!lua name=cc_pause\nredis.register_function(\'cc_pause\', function() return 1 end)'),
            ]
            writes = {'SET', 'INCR', 'PFCOUNT', 'PUBLISH', 'SPUBLISH', 'EVAL'}
            for mode, command in itertools.product(('WRITE', 'ALL'), commands):
                b = peer()
                check('pause armed', a.cmd('CLIENT', 'PAUSE', 180, mode), b'OK')
                b.send(*command)
                held = not bool(select.select([b.sock], [], [], .035)[0])
                check(f'{mode} {command}: postponed', held, mode == 'ALL' or command[0] in writes or
                      command[:2] == ('FUNCTION', 'LOAD'))
                value = b.response()
                rows.append(dict(command=command, reply=clean(value)))
                assert not isinstance(value, RespError), (command, value)
                b.close()
                # In ALL, UNPAUSE itself must wait for expiry.
                check('pause released', a.cmd('CLIENT', 'UNPAUSE'), b'OK')
        elif case == 'disconnect':
            # The KILL acknowledgement is the observable disconnect boundary.
            # Pipeline INFO immediately behind it to expose delayed reclamation.
            for attempt in range(80):
                victims = [peer() for _ in range(4)]
                for v in victims:
                    check('accepted', v.cmd('PING'), b'PONG')
                a.raw(encode('CLIENT', 'KILL', 'SKIPME', 'YES') + encode('INFO', 'clients'))
                check('killed', a.response(), 4)
                body = a.response()
                count = int(re.search(rb'connected_clients:(\d+)', body)[1])
                check(f'connected immediately after KILL {attempt}', count, 1)
                for v in victims:
                    v.close()
        elif case == 'multi-tracking':
            # Enrollment and invalidation follow child execution order, even
            # when a later read re-enrolls a key changed by this same EXEC.
            for reread, noloop in itertools.product((False, True), (False, True)):
                t = peer(3)
                check('ordered tracking on', t.cmd('CLIENT', 'TRACKING', 'ON',
                      *(['NOLOOP'] if noloop else [])), b'OK')
                key = f'cc:ordered:{reread}:{noloop}'.encode()
                check('ordered seed', a.cmd('SET', key, 'v0'), b'OK')
                check('ordered multi', t.cmd('MULTI'), b'OK')
                commands = [('GET', key), ('SET', key, 'v1')]
                if reread:
                    commands.append(('GET', key))
                for command in commands:
                    check('ordered queued', t.cmd(*command), b'QUEUED')
                check('ordered queued silence', keys(t.drain()), [])
                check('ordered exec', t.cmd('EXEC'), [b'v0', b'OK'] + ([b'v1'] if reread else []))
                during = keys(t.drain())
                check('ordered post-write', a.cmd('SET', key, 'v2'), b'OK')
                later = keys(t.drain(.3))
                check('ordered invalidation and re-enrollment', [during, later],
                      [[] if noloop else [key], [key] if reread else []])
                t.close()
            for shape, option, redirect in itertools.product(
                    ('foreign_write_between', 'own_write_first', 'plain_control', 'exec_only'),
                    ('default', 'OPTIN', 'OPTOUT', 'NOLOOP', 'BCAST'), (False, True)):
                t = peer(3)
                sink = peer(3) if redirect else t
                args = [] if option == 'default' else [option]
                if redirect:
                    args += ['REDIRECT', sink.cmd('CLIENT', 'ID')]
                check('tracking on', t.cmd('CLIENT', 'TRACKING', 'ON', *args), b'OK')
                key = ('cc:track:' + shape + ':' + option + str(redirect)).encode()
                check('seed', a.cmd('SET', key, 'v0'), b'OK')
                sink.drain()  # BCAST legitimately invalidates the seed.
                if option == 'OPTIN':
                    check('caching', t.cmd('CLIENT', 'CACHING', 'YES'), b'OK')
                queued_pushes = []
                expected_queued = []
                if shape == 'plain_control':
                    check('plain', t.cmd('GET', key), b'v0')
                else:
                    check('multi', t.cmd('MULTI'), b'OK')
                    if shape == 'own_write_first':
                        check('queued set', t.cmd('SET', key, 'v1'), b'QUEUED')
                    check('queued get', t.cmd('GET', key), b'QUEUED')
                    if shape == 'foreign_write_between':
                        check('between', a.cmd('SET', key, 'v1'), b'OK')
                    queued_pushes = keys(sink.drain())
                    expected_queued = ([key] if option == 'BCAST' and
                                       shape == 'foreign_write_between' else [])
                    expected = [b'OK', b'v1'] if shape == 'own_write_first' else [
                        b'v1' if shape == 'foreign_write_between' else b'v0']
                    check('exec', t.cmd('EXEC'), expected)
                early = keys(sink.drain())
                expected_early = [key] if option == 'BCAST' and shape == 'own_write_first' else []
                check('post-exec write', a.cmd('SET', key, 'v2'), b'OK')
                # Always observe BOTH halves before rejecting PRE: an early
                # invalidation cannot hide a missing post-EXEC invalidation.
                post = keys(sink.drain(.3))
                check('queued / EXEC / post-write invalidations',
                      [queued_pushes, early, post], [expected_queued, expected_early, [key]])
                t.close()
                if redirect:
                    sink.close()
            # CACHING inside MULTI changes the choice for all following child
            # reads; Redis resets it after EXEC, not after each queued child.
            for option, caching, expected in (('OPTIN', 'YES', True), ('OPTIN', None, False),
                                               ('OPTOUT', 'NO', False), ('OPTOUT', None, True)):
                t = peer(3)
                check('on', t.cmd('CLIENT', 'TRACKING', 'ON', option), b'OK')
                check('multi', t.cmd('MULTI'), b'OK')
                if caching:
                    check('queued caching', t.cmd('CLIENT', 'CACHING', caching), b'QUEUED')
                ks = [f'cc:choice:{option}:{caching}:{i}'.encode() for i in range(2)]
                for key in ks:
                    check('queued read', t.cmd('GET', key), b'QUEUED')
                check('exec choices', t.cmd('EXEC'), ([b'OK'] if caching else []) + [None, None])
                check('no early choices', keys(t.drain()), [])
                for key in ks:
                    check('write choice', a.cmd('SET', key, 'v'), b'OK')
                check('choice invalidations', sorted(keys(t.drain(.3))), sorted(ks) if expected else [])
                t.close()
        elif case == 'multi-controls':
            # Reuse AT15's exact RESP2 subscription wire assertion on both arms.
            from at15 import Connection, subscription_policy
            raw = Connection('127.0.0.1', port)
            try:
                rows.append(dict(at15_subscription=clean(subscription_policy(raw, oracle))))
            finally:
                raw.close()
            for proto in (2, 3):
                b = peer(proto)
                check('multi acl', b.cmd('MULTI'), b'OK')
                for command in (('ACL', 'WHOAMI'), ('ACL', 'CAT'), ('ACL', 'USERS')):
                    check('queue acl', b.cmd(*command), b'QUEUED')
                reply = b.cmd('EXEC')
                assert len(reply) == 3 and reply[0] == b'default' and b'default' in reply[2], reply
                rows.append(dict(acl_reply=clean(reply)))
                for sub, unsub in (('SUBSCRIBE', 'UNSUBSCRIBE'), ('PSUBSCRIBE', 'PUNSUBSCRIBE'),
                                   ('SSUBSCRIBE', 'SUNSUBSCRIBE')):
                    check('multi subscription', b.cmd('MULTI'), b'OK')
                    check('queue subscription', b.cmd(sub, 'cc:sub'), b'QUEUED')
                    check('queue unsubscribe', b.cmd(unsub, 'cc:sub'), b'QUEUED')
                    subscribed = (RespError("ERR SSUBSCRIBE isn't allowed for a DENY BLOCKING client")
                                  if sub == 'SSUBSCRIBE' else [sub.lower().encode(), b'cc:sub', 1])
                    check('exec subscription', b.cmd('EXEC'), [
                        subscribed, [unsub.lower().encode(), b'cc:sub', 0]])
                # Ordered publication uses the same EXEC carrier, including
                # delivery to a subscription established by an earlier child.
                check('multi self-publish', b.cmd('MULTI'), b'OK')
                for command in (('SUBSCRIBE', 'cc:self'), ('PUBLISH', 'cc:self', 'msg'),
                                ('UNSUBSCRIBE', 'cc:self')):
                    check('queue self-publish', b.cmd(*command), b'QUEUED')
                check('exec self-publish', b.cmd('EXEC'), [
                    [b'subscribe', b'cc:self', 1], 1, [b'unsubscribe', b'cc:self', 0]])
                check('self-publish delivery', b.drain(), [[b'message', b'cc:self', b'msg']])
                user = f'cc-acl-{proto}'
                check('create ACL caller', a.cmd('ACL', 'SETUSER', user, 'on', 'nopass',
                                               '~*', '&*', '+@all'), b'OK')
                check('authenticate ACL caller', b.cmd('AUTH', user, ''), b'OK')
                check('multi ACL mutation', b.cmd('MULTI'), b'OK')
                for command in (('ACL', 'SETUSER', user, '-set'), ('SET', 'cc:acl-order', 'bad'),
                                ('ACL', 'SETUSER', user, '+set'), ('SET', 'cc:acl-order', 'good'),
                                ('GET', 'cc:acl-order')):
                    check('queue ACL mutation', b.cmd(*command), b'QUEUED')
                denied = RespError('NOPERM ACLs rules changed between the moment the transaction '
                                  'was accumulated and the EXEC call. This command is no longer '
                                  'allowed for the following reason: no permission to execute '
                                  'the command or subcommand')
                check('ordered ACL mutation', b.cmd('EXEC'), [b'OK', denied, b'OK', b'OK', b'good'])
                check('watch ACL abort', b.cmd('WATCH', 'cc:acl-watch'), b'OK')
                check('multi ACL abort', b.cmd('MULTI'), b'OK')
                check('queue aborted ACL', b.cmd('ACL', 'SETUSER', user, '-set'), b'QUEUED')
                check('wound ACL transaction', a.cmd('SET', 'cc:acl-watch', 'changed'), b'OK')
                check('aborted ACL reply', b.cmd('EXEC'), None)
                check('aborted ACL has no effect', b.cmd('SET', 'cc:acl-order', 'still-allowed'), b'OK')
                b.close()
                check('remove ACL caller', a.cmd('ACL', 'DELUSER', user), 1)
        else:
            # Bounded enable-after-OK search. BCAST removes read-enrolment as a
            # confounder; every round proves delivery again on a later write.
            # A miss is a failure; the report distinguishes this search from a
            # proven owner-pass window (which requires an execution certificate).
            t, writer = peer(3), peer()
            for attempt in range(200):
                key = f'cc:enable:{attempt}'.encode()
                check('off', t.cmd('CLIENT', 'TRACKING', 'OFF'), b'OK')
                check('on acknowledged', t.cmd('CLIENT', 'TRACKING', 'ON', 'BCAST'), b'OK')
                check('after OK write', writer.cmd('SET', key, 'v1'), b'OK')
                check('after OK invalidation', keys(t.drain(.01)), [key])
            rows.append(dict(bound=200, owner_pass_window_certified=False))
            # Reuse maxmemrace's observed-owner geometry and bounded LPOS
            # occupation. The tracker and writer parse on an IO distinct from
            # the occupied owner, including in fused mode. This is a finite
            # correctness schedule, without throughput or latency assertions.
            from maxmemrace import Geometry, prepare, LIST_LENGTH, OCCUPY_FIRST, OCCUPY_TASKS
            g = Geometry(port, oracle, rows)
            stack.callback(g.close)
            t.cmd('CLIENT', 'TRACKING', 'OFF')
            if not oracle:
                for _ in range(96):
                    candidate = peer(3)
                    if candidate.cmd('DEBUG', 'IO-THREAD') == g.io:
                        t = candidate
                        break
                    candidate.close()
                else:
                    raise AssertionError('no tracking connection on the selected IO')
            prepare(g, 'noeviction')
            for attempt in range(12):
                check('occupation tracking off', t.cmd('CLIENT', 'TRACKING', 'OFF'), b'OK')
                # The control write crosses an owner pass with tracking off.
                check('old mode settled', g.a.cmd('SET', g.witness, 'settled'), b'+OK')
                scan = encode('LPOS', g.big, LIST_LENGTH - 1)
                g.b1.send(scan * OCCUPY_FIRST)
                g.b2.send(scan * OCCUPY_TASKS)
                check('occupied on acknowledged', t.cmd('CLIENT', 'TRACKING', 'ON', 'BCAST'), b'OK')
                owed = not bool(select.select([g.b2.sock], [], [], 0)[0])
                check('occupied write', g.a.cmd('SET', g.witness, 'after-ok'), b'+OK')
                got = keys(t.drain(.3))
                rows.append(dict(attempt=attempt, occupation_replies_not_ready_at_ok=owed,
                                 invalidations=clean(got)))
                for source, count in ((g.b1, OCCUPY_FIRST), (g.b2, OCCUPY_TASKS)):
                    for _ in range(count):
                        check('occupation executed', source.read(), LIST_LENGTH - 1)
                check('occupied invalidation', got, [g.witness.encode()])
            if not oracle and mode == '2s':
                # The pending TRACKING reply participates in IO drain. Owners
                # must acknowledge ON during that drain, before FLIP can finish.
                check('before flip off', t.cmd('CLIENT', 'TRACKING', 'OFF'), b'OK')
                check('before flip settle', g.a.cmd('SET', g.witness, 'settled'), b'+OK')
                scan = encode('LPOS', g.big, LIST_LENGTH - 1)
                g.b1.send(scan * OCCUPY_FIRST)
                g.b2.send(scan * OCCUPY_TASKS)
                t.send('CLIENT', 'TRACKING', 'ON', 'BCAST')
                a.send('FLIP', 5, 3)
                check('tracking acknowledgement joins flip drain', t.response(), b'OK')
                check('flip completes with tracking acknowledgement', a.response(), b'OK')
                for source, count in ((g.b1, OCCUPY_FIRST), (g.b2, OCCUPY_TASKS)):
                    for _ in range(count):
                        check('flip occupation executed', source.read(), LIST_LENGTH - 1)
                check('post-flip write', a.cmd('SET', g.witness, 'flipped'), b'OK')
                check('post-flip invalidation', keys(t.drain(.3)), [g.witness.encode()])


def main():
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=CASES, required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    failed = 0
    for binary, oracle in ((args.oracle, True), (args.binary, False)):
        run = Run(args, binary, oracle)
        legs = [('redis', 'oracle', 16, 1, 0)] if oracle else itertools.product(
            ('1s', '2s'), ('uring', 'epoll'), (1, 16), (0, 1), (0, 1))
        for mode, engine, db, atomic, local in legs:
            label = f'{mode}-{engine}-db{db}-a{atomic}-r{local}'
            extra = ['--enable-debug-command', 'yes']
            if not oracle:
                extra += ['--net-io', engine, '--databases', str(db), '--atomic', str(atomic),
                          '--read-local', str(local)]
            rows = []
            try:
                with Server(run, label, mode, extra=extra):
                    probe(args.case, args.port, rows, oracle, mode)
                run.check(label, True, True)
            except Exception:
                traceback.print_exc()
                run.check(label, False, True)
            (run.path / (label + '.json')).write_text(json.dumps(rows, indent=2) + '\n')
        failed += run.finish()
    return int(failed != 0)


if __name__ == '__main__':
    raise SystemExit(main())
