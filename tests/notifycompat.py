#!/usr/bin/env python3
"""Ordered Redis 7.4 notification witnesses; run by gate.sh's notifycompat job.

Each case starts on fresh state with active expiry disabled. Silence is checked
with a subscriber barrier and a quiet interval, never by sorting or dropping
frames. Oracle receipts include the actual RESP bytes.
"""
import argparse
import json
import select
import time

from _lib import Conn, encode, info, probe_keys, topology


def equal(got, want, label):
    assert got == want, f'{label}: got {got!r}, expected {want!r}'


class Capture:
    def __init__(self, file):
        self.file, self.wire = file, bytearray()

    def read(self, count):
        value = self.file.read(count)
        self.wire.extend(value)
        return value

    def readline(self, *args):
        value = self.file.readline(*args)
        self.wire.extend(value)
        return value

    def close(self):
        self.file.close()


class Peer:
    def __init__(self, host, port, target=False, args=None):
        self.target = target
        self.failures = []
        self.keysets = args.keysets if args else []
        self.admin = Conn(host, port, buffering=0, timeout=5)
        self.driver = Conn(host, port, buffering=0, timeout=5)
        self.sub = Conn(host, port, buffering=0, timeout=5)
        self.sub.file = Capture(self.sub.file)
        self.configure('')
        equal(self.admin.cmd('FLUSHALL'), b'OK', 'fresh DB')
        equal(self.admin.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0), b'OK', 'disable active expiry')
        if target:
            observed = info(self.admin, 'server')
            wanted = dict(thread_mode=args.mode, net_io=args.engine, atomic=str(args.atomic),
                          read_local=str(args.read_local), shards='16')
            for field, value in wanted.items():
                equal(observed[field], value, 'geometry ' + field)
            roles = list(topology(self.admin).roles.values())
            equal((roles.count('io'), roles.count('ex'), roles.count('fused')),
                  (6, 2, 0) if args.mode == '2s' else (0, 0, 8), 'actual thread geometry')
            print('GEOMETRY ' + json.dumps(wanted), flush=True)
        else:
            equal(info(self.admin, 'server')['redis_version'], '7.4.10', 'oracle version')
        self.sub.send('PSUBSCRIBE', '__keyspace@*__:*', '__keyevent@*__:*')
        equal(self.sub.read(), [b'psubscribe', b'__keyspace@*__:*', 1], 'keyspace ACK')
        equal(self.sub.read(), [b'psubscribe', b'__keyevent@*__:*', 2], 'keyevent ACK')

    def configure(self, flags):
        equal(self.admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', flags), b'OK', 'notify config')

    def drain(self, count):
        frames, wires = [], []
        def read():
            self.sub.file.wire.clear()
            value = self.sub.read()
            return value, bytes(self.sub.file.wire)
        deadline = time.monotonic() + 2
        while len(frames) < count and time.monotonic() < deadline:
            if select.select([self.sub.sock], [], [], max(0, deadline - time.monotonic()))[0]:
                value, wire = read()
                frames.append(value)
                wires.append(wire)
        self.sub.send('PING', 'notifycompat-barrier')
        while True:
            value, wire = read()
            if value == [b'pong', b'notifycompat-barrier']:
                break
            frames.append(value)
            wires.append(wire)
        while select.select([self.sub.sock], [], [], .04)[0]:
            value, wire = read()
            frames.append(value)
            wires.append(wire)
        return frames, b''.join(wires)

    def setup(self, *commands):
        self.configure('')
        for command in commands:
            result = self.driver.cmd(*command)
            assert not isinstance(result, Exception), (command, result)
        equal(self.drain(0), ([], b''), 'silent setup')
        self.configure('KEAm')

    def step(self, label, command, reply, events, db=0):
        want = []
        for event, key in events:
            event, key = event.encode(), key.encode()
            want += [[b'pmessage', b'__keyspace@*__:*', f'__keyspace@{db}__:'.encode() + key, event],
                     [b'pmessage', b'__keyevent@*__:*', f'__keyevent@{db}__:'.encode() + event, key]]
        got_reply = self.driver.cmd(*command)
        got, wire = self.drain(len(want))
        result = dict(target=self.target, label=label, command=command, reply=repr(got_reply),
                      frames=repr(got), wire_hex=wire.hex(), expected=repr(want))
        print(json.dumps(result), flush=True)
        for got_value, want_value, field in (
                (got_reply, reply, 'reply'), (got, want, 'ordered frames'),
                (wire, b''.join(encode(*frame) for frame in want), 'wire bytes')):
            try:
                equal(got_value, want_value, label + ' ' + field)
            except AssertionError as error:
                self.failures.append(str(error))
        return wire

    def close(self):
        try:
            self.configure('')
            self.admin.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 1)
        finally:
            for conn in (self.sub, self.driver, self.admin):
                conn.close()


def setbit(peer):
    peer.setup(('SET', 'nc:raw', 'x' * 80), ('SET', 'nc:int', '5'))
    peer.admin.cmd('CONFIG', 'SET', 'save', '3600 1')
    before = int(info(peer.admin, 'persistence')['rdb_changes_since_last_save'])
    peer.step('raw unchanged', ('SETBIT', 'nc:raw', 0, 0), 0, [])
    peer.step('integer unchanged', ('SETBIT', 'nc:int', 0, 0), 0, [])
    after = int(info(peer.admin, 'persistence')['rdb_changes_since_last_save'])
    if after != before:
        peer.failures.append(f'unchanged SETBIT dirty delta: {after-before}, expected 0')
    peer.step('changed bit', ('SETBIT', 'nc:raw', 0, 1), 0, [('setbit', 'nc:raw')])
    peer.step('growth with zero', ('SETBIT', 'nc:int', 8, 0), 0, [('setbit', 'nc:int')])
    peer.step('new zero bit', ('SETBIT', 'nc:new', 0, 0), 0, [('setbit', 'nc:new')])
    after = int(info(peer.admin, 'persistence')['rdb_changes_since_last_save'])
    if after - before != 3:
        peer.failures.append(f'changed SETBIT dirty delta: {after-before}, expected 3')
    peer.admin.cmd('CONFIG', 'SET', 'save', '')


def setpast(peer):
    for option in ('EXAT', 'PXAT'):
        for present in (False, True):
            key = f'nc:past:{option}:{present}'
            peer.setup(*([('SET', key, 'old')] if present else []))
            peer.step('SET elapsed ' + key, ('SET', key, 'value', option, 1), b'OK',
                      [('set', key), ('expire', key)])
            peer.step('lazy expiry ' + key, ('GET', key), None,
                      [('expired', key), ('keymiss', key)])
        key = f'nc:getex:{option}'
        peer.setup(('SET', key, 'value'))
        peer.step('GETEX past control', ('GETEX', key, option, 1), b'value', [('del', key)])
    peer.setup()
    peer.step('XX absent control', ('SET', 'nc:xx', 'v', 'XX', 'PXAT', 1), None, [])
    peer.setup(('SET', 'nc:nx', 'v'))
    peer.step('NX present control', ('SET', 'nc:nx', 'v', 'NX', 'EXAT', 1), None, [])


def emptystore(peer):
    for layout, (dst, src, other) in enumerate(peer.keysets):
        for command in (('BITOP', 'AND', dst, src), ('SINTERSTORE', dst, src),
                        ('SUNIONSTORE', dst, src), ('SDIFFSTORE', dst, src)):
            peer.setup(('FLUSHALL',))
            peer.step(f'absent destination layout={layout}', command, 0, [('keymiss', src)])
            peer.setup(('SET', dst, 'old'))
            peer.step(f'live destination layout={layout}', command, 0,
                      [('keymiss', src), ('del', dst)])


def writemiss(peer):
    for name in ('SET', 'GETSET', 'GETDEL', 'GETEX'):
        for expired in (False, True):
            key = f'nc:readwrite:{name}:{expired}'
            if expired:
                peer.setup(('SET', key, 'old', 'PX', 50))
                time.sleep(.08)
            else:
                peer.setup()
            command = (name, key) + (('new', 'GET') if name == 'SET' else
                                     ('new',) if name == 'GETSET' else ())
            events = ([('expired', key)] if expired else []) + [('keymiss', key)]
            if name in ('SET', 'GETSET'):
                events.append(('set', key))
            peer.step('write read miss ' + key, command, None, events)
    peer.setup()
    peer.step('plain SET has no read miss', ('SET', 'nc:writeonly', 'v'), b'OK',
              [('set', 'nc:writeonly')])
    peer.step('SET XX GET misses before condition', ('SET', 'nc:xxget', 'v', 'XX', 'GET'),
              None, [('keymiss', 'nc:xxget')])


def objectmiss(peer):
    for sub in ('ENCODING', 'REFCOUNT', 'IDLETIME', 'FREQ'):
        policy = 'allkeys-lfu' if sub == 'FREQ' else 'allkeys-lru'
        equal(peer.admin.cmd('CONFIG', 'SET', 'maxmemory-policy', policy), b'OK', 'policy')
        for expired in (False, True):
            key = f'nc:object:{sub}:{expired}'
            peer.setup(*([('SET', key, 'value', 'PX', 50)] if expired else []))
            if expired:
                time.sleep(.08)
            peer.step('OBJECT read ' + key, ('OBJECT', sub, key), None,
                      [('expired', key)] if expired else [])
    # Redis resolves a missing/expired key before checking whether the policy
    # supports the requested statistic.
    for sub, policy in (('IDLETIME', 'allkeys-lfu'), ('FREQ', 'allkeys-lru')):
        equal(peer.admin.cmd('CONFIG', 'SET', 'maxmemory-policy', policy), b'OK', 'policy')
        key = 'nc:policy:' + sub
        peer.setup()
        peer.step('absent before policy error', ('OBJECT', sub, key), None, [])
    peer.admin.cmd('CONFIG', 'SET', 'maxmemory-policy', 'noeviction')


def expiredstore(peer):
    for layout, (dst, src, other) in enumerate(peer.keysets):
        cases = [
            (('BITOP', 'AND', dst, src), [], [('keymiss', src)]),
            (('SINTERSTORE', dst, src, other), [('SADD', src, 'a'), ('SADD', other, 'b')], []),
            (('SUNIONSTORE', dst, src), [], [('keymiss', src)]),
            (('SDIFFSTORE', dst, src, src), [('SADD', src, 'a')], []),
            (('ZINTERSTORE', dst, 2, src, other), [('ZADD', src, 1, 'a'), ('ZADD', other, 2, 'b')], []),
            (('ZUNIONSTORE', dst, 1, src), [], [('keymiss', src)]),
            (('ZDIFFSTORE', dst, 2, src, src), [('ZADD', src, 1, 'a')], []),
            (('ZRANGESTORE', dst, src, 10, 20), [('ZADD', src, 1, 'a')], []),
            (('SORT', src, 'LIMIT', 10, 1, 'STORE', dst), [('RPUSH', src, 1)], []),
            (('GEOSEARCHSTORE', dst, src, 'FROMLONLAT', 20, 20, 'BYRADIUS', 1, 'm'),
             [('GEOADD', src, 0, 0, 'home')], []),
            (('GEORADIUS', src, 20, 20, 1, 'm', 'STORE', dst), [('GEOADD', src, 0, 0, 'home')], []),
        ]
        for command, setup, source_events in cases:
            peer.setup(('FLUSHALL',), *setup, ('SET', dst, 'elapsed', 'PX', 50))
            time.sleep(.08)
            assert isinstance(peer.driver.cmd('MEMORY', 'USAGE', dst), int), 'expired resident window never opened'
            before = int(info(peer.admin, 'stats')['expired_keys'])
            peer.step(f'expired destination layout={layout}', command, 0, source_events + [('del', dst)])
            after = int(info(peer.admin, 'stats')['expired_keys'])
            if after != before:
                peer.failures.append(f'{command}: explicit deletion counted as expiry ({before} -> {after})')



CASES = {'setbit': setbit, 'setpast': setpast, 'emptystore': emptystore,
         'writemiss': writemiss, 'objectmiss': objectmiss, 'expiredstore': expiredstore}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    parser.add_argument('--oracle', nargs=2)
    parser.add_argument('--case', choices=CASES, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--engine', choices=('epoll', 'uring'), default='epoll')
    parser.add_argument('--atomic', type=int, default=0)
    parser.add_argument('--read-local', type=int, default=0)
    args = parser.parse_args()
    args.keysets = [('nc:local:dst', 'nc:local:src', 'nc:local:other'),
                    ('nc:cross:dst', 'nc:cross:src', 'nc:cross:other')]
    if args.oracle and args.case in ('emptystore', 'expiredstore'):
        chooser = Conn(args.host, args.port)
        try:
            topo = topology(chooser)
            buckets, cross, owners = {}, [], set()
            for key, shard, owner in probe_keys(chooser, 'nc:route', topo):
                buckets.setdefault(shard, []).append(key)
                if owner not in owners and len(cross) < 2:
                    cross.append(key)
                    owners.add(owner)
                if len(cross) == 2 and any(len(keys) >= 3 for keys in buckets.values()):
                    same = next(keys[:3] for keys in buckets.values() if len(keys) >= 3)
                    args.keysets = [same, cross + [same[0]]]
                    break
            else:
                raise AssertionError('could not arm local and cross-owner keys')
        finally:
            chooser.close()
    addresses = [(args.oracle[0], int(args.oracle[1]), False), (args.host, args.port, True)] \
        if args.oracle else [(args.host, args.port, False)]
    for host, port, target in addresses:
        peer = Peer(host, port, target, args)
        try:
            CASES[args.case](peer)
            assert not peer.failures, '\n'.join(peer.failures)
        finally:
            peer.close()
    print('PASS ' + args.case, flush=True)


if __name__ == '__main__':
    main()
