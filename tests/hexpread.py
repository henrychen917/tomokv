#!/usr/bin/env python3
"""Hash reads of parked MVCC versions: replies, immutable expiry and deferred reaping.

Owns its server, sockets and artifact directory. Every held-group arm requires two
installed entries, an unanswered group and a live pre-deadline field. Missed arms
are retried on fresh state at most three times, then fail. No timing assertion is
relaxed for PRE or for a failed arm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import select
import time

import aoffix2 as h
import _lib


class Client(h.Client):
    def read(self):
        line = self.f.readline()
        if not line:
            raise EOFError('server closed connection')
        tag, body = line[:1], line[1:-2]
        if tag == b'-':
            raise RuntimeError(body.decode())
        if tag == b'+':
            return body
        if tag == b':':
            return int(body)
        if tag == b'_':
            return None
        if tag == b'%':
            return {self.read(): self.read() for _ in range(int(body))}
        if tag in (b'*', b'>', b'~'):
            count = int(body)
            return None if count < 0 else [self.read() for _ in range(count)]
        if tag == b'$':
            count = int(body)
            if count < 0:
                return None
            value = self.f.read(count)
            assert len(value) == count and self.f.read(2) == b'\r\n'
            return value
        raise AssertionError(line)


h.Client = Client


def stats(client):
    return {k: int(v) for line in client.cmd('INFO', 'stats').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)] if v.isdigit()}


def wait_for(predicate, reason, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(.005)
    raise AssertionError(reason)


def keys(client):
    owners = _lib.topology(client).shard_owner
    chosen = {}
    for i in range(4096):
        key = f'hexpread:{i}'
        sid = client.cmd('DEBUG', 'SHARD', key)
        chosen.setdefault(owners[sid], (key, sid))
        if len(chosen) == 2:
            a, b = list(chosen.values())
            sentinel = next(k for j in range(4096)
                            if client.cmd('DEBUG', 'SHARD', (k := f'hexpread:keep:{j}')) == a[1])
            h.emit('geometry', owners=chosen, sentinel=sentinel)
            return a[0], b[0], sentinel
    raise AssertionError('two distinct owners were not found')


def subscribe(server):
    sub = server.client()
    channels = [f'__keyevent@0__:{name}' for name in ('hexpired', 'del')]
    sub.send('SUBSCRIBE', *channels)
    for channel in channels:
        assert sub.read()[1] == channel.encode()
    return sub


def events(sub, required=0):
    # A PING on this pubsub connection is an ordered barrier, not a socket-readiness
    # guess (BufferedReader can already have the next message in its own buffer).
    result = []
    # Owner notifications can arrive after the command reply on another I/O thread.
    # A positive check must receive its promised events before placing the drain barrier.
    # Missing events time out as failures; they are never treated as an empty successful drain.
    for _ in range(required):
        row = sub.read()
        assert row[0] == b'message', row
        result.append([row[1].split(b':')[-1].decode(), row[2].decode()])
    sub.send('PING', 'hexpread-barrier')
    while True:
        row = sub.read()
        if row == [b'pong', b'hexpread-barrier']:
            return result
        assert row[0] == b'message', row
        result.append([row[1].split(b':')[-1].decode(), row[2].decode()])


def deadline_passed(deadline):
    while time.time_ns() // 1_000_000 <= deadline + 20:
        time.sleep(.005)


def arm(server, admin, group, sub, *, partial=False, sentinel=True, rename=False):
    a, b, keep = keys(admin)
    for attempt in range(3):
        assert admin.cmd('FLUSHDB') == b'OK'
        assert admin.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
        assert admin.cmd('HSET', a, 'f', 'old') == 1
        if partial:
            assert admin.cmd('HSET', a, 'g', 'keep') == 1
        if rename:
            assert admin.cmd('HSET', b, 'f', 'candidate') == 1
        if sentinel:
            assert admin.cmd('HSET', keep, 'f', 'sentinel') == 1
            assert admin.cmd('HPEXPIRE', keep, 60000, 'FIELDS', 1, 'f') == [1]
        deadline = time.time_ns() // 1_000_000 + 700
        assert admin.cmd('HPEXPIREAT', a, deadline, 'FIELDS', 1, 'f') == [1]
        if rename:
            assert admin.cmd('HPEXPIREAT', b, deadline, 'FIELDS', 1, 'f') == [1]
        events(sub)
        before = stats(admin)
        assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1) == b'OK'
        group.send(*(['RENAME', b, a] if rename else ['MSET', a, '1', b, '1']))
        installed = wait_for(lambda: (s if (s := stats(admin))['atomic_pending_entries'] >= 2
                                     else None), 'group never installed on both owners')
        assert not select.select([group.s], [], [], 0)[0], 'held group already replied'
        live = admin.cmd('HGET', a, 'f')
        if live == b'old' and time.time_ns() // 1_000_000 < deadline:
            h.emit('armed', attempt=attempt, deadline=deadline, a=a, b=b,
                   partial=partial, sentinel=sentinel, rename=rename,
                   before=before, installed=installed, live=live)
            return a, b, deadline, before
        assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == b'OK'
        assert group.read() == b'OK'
        h.emit('missed_arm', attempt=attempt, live=live)
    raise AssertionError('three fresh arms missed the live field window')


def check_replies(reader, a, partial, resp):
    live = b'keep' if partial else None
    checks = [(['HGET', a, 'f'], None), (['HGET', a, 'g'], live),
              (['HMGET', a, 'f', 'g', 'missing'], [None, live, None]),
              (['HEXISTS', a, 'f'], 0), (['HEXISTS', a, 'g'], int(partial)),
              (['HSTRLEN', a, 'f'], 0), (['HLEN', a], int(partial)),
              (['HKEYS', a], [b'g'] if partial else []),
              (['HVALS', a], [b'keep'] if partial else []),
              (['HGETALL', a], ({b'g': b'keep'} if partial else {}) if resp == 3 else
                               ([b'g', b'keep'] if partial else [])),
              (['HRANDFIELD', a], b'g' if partial else None),
              (['HRANDFIELD', a, 5], [b'g'] if partial else []),
              (['HRANDFIELD', a, -8], [b'g'] * 8 if partial else []),
              (['HRANDFIELD', a, -4, 'WITHVALUES'],
               (([[b'g', b'keep']] * 4 if resp == 3 else [b'g', b'keep'] * 4)
                if partial else []))]
    for cmd in ('HTTL', 'HPTTL', 'HEXPIRETIME', 'HPEXPIRETIME'):
        checks.append(([cmd, a, 'FIELDS', 3, 'f', 'g', 'missing'],
                       [-2, -1 if partial else -2, -2]))
    for command, expected in checks:
        actual = reader.cmd(*command)
        h.emit('reply_check', command=command, actual=actual, expected=expected)
        assert actual == expected, (command, actual, expected)
    for options in ([], ['NOVALUES'], ['MATCH', 'f']):
        cursor, found = b'0', []
        for _ in range(128):
            cursor, chunk = reader.cmd('HSCAN', a, cursor, 'COUNT', 1, *options)
            found.extend(chunk)
            if cursor == b'0':
                break
        else:
            raise AssertionError('HSCAN did not finish')
        expected = [] if not partial or options == ['MATCH', 'f'] else (
            [b'g'] if options == ['NOVALUES'] else [b'g', b'keep'])
        assert found == expected, (options, found, expected)


def run_case(server):
    admin, group, reader = (server.client(timeout=10) for _ in range(3))
    assert admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'Egh') == b'OK'
    sub = subscribe(server)
    case = h.ARGS.case
    forms = [(False, True, 512, 2)] if case != 'replies' else [
        (partial, sentinel, limit, resp) for partial in (False, True)
        for sentinel, limit, resp in ((True, 512, 2), (False, 0, 3))]
    for partial, sentinel, limit, resp in forms:
        assert admin.cmd('CONFIG', 'SET', 'hash-max-listpack-entries', limit) == b'OK'
        reader.cmd('HELLO', resp)
        try:
            a, b, deadline, before = arm(server, admin, group, sub, partial=partial,
                                          sentinel=sentinel, rename=case == 'deferred')
            deadline_passed(deadline)
            if case == 'replies':
                check_replies(reader, a, partial, resp)
            else:
                assert reader.cmd('HGET', a, 'f') is None
            assert not select.select([group.s], [], [], 0)[0], 'group escaped commit hold'
            during, early = stats(admin), events(sub)
            h.emit('held_read', before=before, during=during, events=early)
        finally:
            assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == b'OK'
        assert group.read() == b'OK'
        if case == 'torn':
            actual = admin.cmd('MGET', a, b)
            h.emit('committed', actual=actual)
            assert actual == [b'1', b'1'], 'expired hash read erased an atomic MSET candidate'
        elif case == 'replies':
            assert during['expired_hash_fields'] == before['expired_hash_fields'], \
                'read physically reaped a parked version'
            assert early == [], 'parked read emitted expiry notifications'
            assert admin.cmd('MGET', a, b) == [b'1', b'1']
        else:
            # The committed RENAME installed a fresh hash with the same deadline. Only
            # this subsequent safe access may reap it and emit hexpired, then del.
            before_later = stats(admin)
            commit_events = events(sub)
            assert admin.cmd('HGET', a, 'f') is None
            after_later, later = stats(admin), events(sub, required=2)
            h.emit('deferred_reap', before=before_later, after=after_later,
                   commit_events=commit_events, events=later)
            assert after_later['expired_hash_fields'] - before_later['expired_hash_fields'] == 1
            assert later == [['hexpired', a], ['del', a]], later
            assert during['expired_hash_fields'] == before['expired_hash_fields'] and not early
            assert after_later['expired_keys'] == before['expired_keys']
            if h.ARGS.policy != 'off':
                assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
                assert admin.cmd('EXISTS', a, b) == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--case', choices=('torn', 'replies', 'deferred'), required=True)
    parser.add_argument('--policy', choices=('off', 'always'), default='off')
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.artifacts = args.artifacts.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    args.oracle, args.engine, args.databases = False, 'uring', 16
    h.ARGS = args
    h.emit('arm', binary=str(args.binary),
           sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
           case=args.case, mode=args.mode, policy=args.policy)
    with h.Server(h.aof() + ['--atomic', '1', '--databases', '16']) as server:
        run_case(server)
    h.emit('pass', case=args.case)


if __name__ == '__main__':
    main()
