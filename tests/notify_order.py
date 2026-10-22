#!/usr/bin/env python3
"""Exact lazy-expiry frames against Redis 7.4.10; invoked by job_notify_order.

The MGET publisher shares a coordinator with at least two expiring keys. PRE's
single keymiss chain cannot interleave their keyless chains, regardless of timing.
No sorting, timing tolerance, skipped arm, or event-order retry is permitted.
"""
import argparse
import json
from pathlib import Path
import select
import time

from _lib import Conn, info, lbsignals, probe_keys, shard_of, topology


def equal(got, want, label):
    assert got == want, f"{label}: got {got!r}, expected {want!r}"


def poll(predicate, label, seconds=10):
    end = time.monotonic() + seconds
    while True:
        result = predicate()
        if result:
            return result
        assert time.monotonic() < end, label
        time.sleep(.002)


def frames(events):
    out = []
    for event, key in events:
        key = key.encode() if isinstance(key, str) else key
        event = event.encode()
        out += [[b'pmessage', b'__keyspace@0__:*', b'__keyspace@0__:' + key, event],
                [b'pmessage', b'__keyevent@0__:*', b'__keyevent@0__:' + event, key]]
    return out


def barrier(conn):
    conn.send('PING', 'notifyorder-barrier')
    seen = []
    end = time.monotonic() + 5
    while True:
        assert time.monotonic() < end, 'subscriber PING barrier timed out'
        value = conn.read()
        if value == [b'pong', b'notifyorder-barrier']:
            return seen
        seen.append(value)


class Peer:
    def __init__(self, host, port, target=False, expected=None):
        self.host, self.port, self.target = host, int(port), target
        self.admin = Conn(host, port, buffering=0, timeout=5)
        self.driver = None
        self.listener = Conn(host, port, buffering=0, timeout=5)
        self.held = []
        self.coordinator_owner = None
        if target:
            self.topo = topology(self.admin)
            mode, engine, atomic, read_local = expected
            observed = info(self.admin, 'server')
            wanted = dict(thread_mode=mode, net_io=engine, atomic=str(atomic),
                          read_local=str(read_local), shards='16', key_lb='0',
                          client_lb='0', flip_auto='0')
            for field, value in wanted.items():
                equal(observed.get(field), value, 'declared geometry ' + field)
            equal(len(self.topo.roles), 8, 'eight actual threads')
            equal(len(self.topo.shard_owner), 16, 'sixteen actual shards')
            equal(self.topo.mode, mode, 'LBSIGNALS mode')
            roles = {role: list(self.topo.roles.values()).count(role) for role in ('io', 'ex', 'fused')}
            equal(roles, dict(io=6, ex=2, fused=0) if mode == '2s' else dict(io=0, ex=0, fused=8),
                  'actual 6:2 split or eight fused threads')
            print('GEOMETRY observed=' + json.dumps(wanted), flush=True)
            ios = sorted(t for t, role in self.topo.roles.items() if role in ('io', 'fused'))
            coordinators = {ios[owner % len(ios)]: owner for owner in self.topo.owners}
            # Observe the accepted connection's IO in the actual boot. Hold rejected
            # connections until selection ends, so asynchronous closes cannot obscure +1.
            prior = {t.tid: t.clients for t in lbsignals(self.admin).threads}
            for attempt in range(64):
                candidate = Conn(host, port, buffering=0, timeout=5)
                equal(candidate.cmd('PING'), b'PONG', 'publisher readiness')
                current = {t.tid: t.clients for t in lbsignals(self.admin).threads}
                changed = [tid for tid in current if current[tid] == prior[tid] + 1]
                equal(sum(current.values()) - sum(prior.values()), 1, 'one accepted publisher')
                equal(len(changed), 1, 'publisher IO witness')
                prior = current
                if changed[0] in coordinators:
                    self.driver = candidate
                    self.coordinator_owner = coordinators[changed[0]]
                    print(f'GEOMETRY publisher_io={changed[0]} keyless_owner={self.coordinator_owner}', flush=True)
                    break
                self.held.append(candidate)
            assert self.driver, 'could not arm a publisher on a keyless coordinator'
        else:
            equal(info(self.admin, 'server')['redis_version'], '7.4.10', 'oracle version')
            self.driver = Conn(host, port, buffering=0, timeout=5)
        equal(self.admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', ''), b'OK', 'silence setup')
        equal(self.admin.cmd('FLUSHALL'), b'OK', 'fresh DB')
        equal(self.admin.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0), b'OK', 'active expiry disabled')
        self.listener.send('PSUBSCRIBE', '__keyspace@0__:*', '__keyevent@0__:*')
        equal(self.listener.read(), [b'psubscribe', b'__keyspace@0__:*', 1], 'keyspace ACK')
        equal(self.listener.read(), [b'psubscribe', b'__keyevent@0__:*', 2], 'keyevent ACK')

    def configure(self, flags):
        equal(self.admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', flags), b'OK', 'notify config')

    def quiesce(self, atomic=False):
        if self.target:
            # atomic_entries is cumulative (atomic_link_entry only increments it).
            # atomic_pending_entries is the live MVCC gauge needed by this arm.
            def idle():
                stats = info(self.admin)
                keys = ('atomic_inflight', 'atomic_pending_entries', 'pubsub_inflight') if atomic else ('pubsub_inflight',)
                return all(int(stats[k]) == 0 for k in keys)
            poll(idle, 'atomic/notification state did not quiesce')

    def counters(self):
        stats = info(self.admin)
        keys = ['expired_keys'] + (['notify_events_fired', 'notify_events_dropped'] if self.target else [])
        return {key: int(stats[key]) for key in keys}

    def clock(self):
        sec, usec = self.admin.cmd('TIME')
        return int(sec) * 1000 + int(usec) // 1000

    def collect(self, count):
        out = []
        end = time.monotonic() + 5
        while len(out) < count and time.monotonic() < end:
            if select.select([self.listener.sock], [], [], max(0, end-time.monotonic()))[0]:
                out.append(self.listener.read())
        self.quiesce()
        out += barrier(self.listener)
        # A keyless post can still be in flight before its first reservation. Keep
        # a bounded quiet check as well as the positive count and FIFO barrier.
        if select.select([self.listener.sock], [], [], .03)[0]:
            out.append(self.listener.read())
            out += barrier(self.listener)
        return out

    def close(self):
        try:
            self.configure('')
            equal(self.admin.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 1), b'OK', 'restore expiry')
        finally:
            for conn in [self.listener, self.driver, self.admin] + self.held:
                if conn:
                    conn.close()


def choose(target, prefix, kind):
    if kind not in ('C2', 'C7', 'A5'):
        return [prefix]
    if kind == 'A5':
        first = None
        for key, sid, _owner in probe_keys(target.admin, prefix, target.topo):
            if first is None:
                first = (key, sid)
            elif sid == first[1]:
                return [first[0], key]
    if kind == 'C7':
        first = None
        for key, _sid, owner in probe_keys(target.admin, prefix, target.topo):
            if first is None:
                first = (key, owner)
            elif owner != first[1]:
                return [first[0], key]
    # Four keys on the publisher's keyless coordinator, four on other owners.
    local, other, shards = [], [], set()
    for key, sid, owner in probe_keys(target.admin, prefix, target.topo):
        bucket = local if owner == target.coordinator_owner else other
        if len(bucket) < 4:
            bucket.append((key, sid, owner))
            shards.add(sid)
        if len(local) == len(other) == 4 and len(shards) >= 3:
            rows = local + other
            assert len({row[2] for row in rows}) >= 2
            print('C2 shards/owners=' + repr(rows), flush=True)
            return [row[0] for row in rows] + [prefix + ':live']
    raise AssertionError('required key geometry never opened')


def specification(kind, keys):
    key = keys[0]
    if kind == 'C2':
        expired = keys[:8]
        args = expired[:3] + [keys[8]] + expired[3:]
        return ('MGET', *args), [None]*3 + [b'live'] + [None]*5, [(ev, k) for k in expired for ev in ('expired', 'keymiss')], 8
    if kind == 'C7':
        return ('MSETNX', key, 'v', keys[1], 'v'), 0, [('expired', key)], 1
    if kind == 'C8':
        return ('HGET', key, 'f'), None, [('hexpired', key), ('del', key)], 0
    if kind == 'C6':
        return ('DEL', key), 0, [('expired', key)], 1
    events = [('expired', key)]
    if kind in ('C1', 'C4', 'C5'):
        events += [('keymiss', key)]
    if kind in ('C3', 'C4', 'C5'):
        events += [('new', key), ('set', key)]
    cmd = {'C1': ('GET', key), 'C3': ('SET', key, 'v2'),
           'C4': None, 'C5': ('EVAL', "redis.call('GET',KEYS[1]); return redis.call('SET',KEYS[1],'v')", 1, key)}[kind]
    reply = {'C1': None, 'C3': b'OK', 'C4': [None, b'OK'], 'C5': b'OK'}[kind]
    return cmd, reply, events, 1


def run_case_once(peers, kind, trial, window):
    # Retry ONLY arming, on fresh keys; any access/result/frame failure is final.
    for attempt in range(8):
        keys = choose(peers[0], f'notifyorder:{kind}:{trial}:{window}:{attempt}', kind)
        live, deadlines = True, []
        for peer in peers:
            peer.configure('')
            equal(peer.admin.cmd('FLUSHALL'), b'OK', 'fresh trial state')
            peer.quiesce(atomic=True)
            equal(barrier(peer.listener), [], 'clean setup subscriber')
            expired = keys[:8] if kind == 'C2' else keys[:1]
            if kind in ('C2', 'C7'):
                equal(peer.driver.cmd('SET', keys[-1], 'live'), b'OK', 'live companion')
            due = []
            for key in expired:
                if kind == 'C8':
                    equal(peer.driver.cmd('HSET', key, 'f', 'v'), 1, 'hash arm')
                    equal(peer.driver.cmd('HPEXPIRE', key, 100, 'FIELDS', 1, 'f'), [1], 'field TTL')
                    live &= peer.driver.cmd('HGET', key, 'f') == b'v'
                    deadline = peer.driver.cmd('HPEXPIRETIME', key, 'FIELDS', 1, 'f')[0]
                else:
                    equal(peer.driver.cmd('SET', key, 'v', 'PX', 100), b'OK', 'PX arm')
                    live &= peer.driver.cmd('GET', key) == b'v'
                    deadline = peer.driver.cmd('PEXPIRETIME', key)
                live &= isinstance(deadline, int) and deadline > 0
                due.append(deadline)
            deadlines.append(max(due))
        if live:
            break
    else:
        raise AssertionError(f'{kind}: live expiry window never opened')
    cmd, reply, events, expired_count = specification(kind, keys)
    before = []
    for peer, due in zip(peers, deadlines):
        # A-normalization currently drops n on TomoKV CONFIG SET; spell out
        # the classes this row observes so New is actually armed on both peers.
        peer.configure('g$lhxKEmn')
        peer.quiesce(atomic=True)
        before.append(peer.counters())
        poll(lambda: peer.clock() > due + 2, 'server expiry clock did not advance')
        peer.quiesce(atomic=True)
        equal(barrier(peer.listener), [], 'no event before lazy access')
        equal(peer.counters(), before[-1], 'lazy counters flat')
    results = []
    for peer, old in zip(peers, before):
        if kind == 'C4':
            equal(peer.driver.cmd('MULTI'), b'OK', 'MULTI')
            equal(peer.driver.cmd('GET', keys[0]), b'QUEUED', 'queued GET')
            equal(peer.driver.cmd('SET', keys[0], 'v'), b'QUEUED', 'queued SET')
            actual = peer.driver.cmd('EXEC')
        else:
            actual = peer.driver.cmd(*cmd)
        if kind == 'C7' and peer.target:
            peer.quiesce(atomic=True)
            now = peer.counters()
            if now['expired_keys'] == old['expired_keys']:
                # The live-key owner can abort before the other fragment starts.
                # This is an unopened physical-deletion window, not a delivery
                # failure: demand zero effects and re-arm on fresh state, bounded.
                equal(actual, 0, 'C7 cancelled reply')
                equal(peer.collect(0), [], 'C7 unopened window has no frames')
                equal(peer.counters(), old, 'C7 unopened window has no effects')
                print(f'ARM MISS C7/{trial}/{window}: cancelled before expiry', flush=True)
                return False
        got = peer.collect(2*len(events))
        now = peer.counters()
        result = dict(reply=repr(actual), frames=repr(got), counters=now)
        results.append(result)
        print(json.dumps(dict(case=kind, trial=trial, target=peer.target, **result)), flush=True)
        equal(actual, reply, kind + ' reply')
        equal(now['expired_keys'] - old['expired_keys'], expired_count, kind + ' physical deletions')
        if peer.target:
            # fired counts records when made, including the speculative New
            # which atomic MSETNX later discards. It is not a delivery counter.
            speculative = int(kind == 'C7' and int(peer.admin.cmd('CONFIG', 'GET', 'atomic')[1]) != 0)
            equal(now['notify_events_fired'] - old['notify_events_fired'],
                  len(events) + speculative, kind + ' fired (including speculative New)')
            equal(now['notify_events_dropped'], old['notify_events_dropped'], kind + ' no drops')
    # Run both sides even on an ordering failure, preserving the oracle evidence.
    print(json.dumps(dict(case=kind, trial=trial, target=results[0], oracle=results[1])), flush=True)
    equal(results[1]['frames'], repr(frames(events)), kind + ' oracle hard-coded frames')
    equal(results[0]['frames'], results[1]['frames'], kind + ' ordered differential')
    return True


def run_case(peers, kind, trial):
    for window in range(8 if kind == 'C7' else 1):
        if run_case_once(peers, kind, trial, window):
            return
    raise AssertionError('C7: physical deletion before cross-owner abort never opened')


def tracking_case(peers):
    for peer in peers:
        peer.configure('')
        tracker = Conn(peer.host, peer.port, buffering=0, timeout=5)
        witness = Conn(peer.host, peer.port, buffering=0, timeout=5)
        try:
            tracker.cmd('HELLO', 3)
            witness.cmd('HELLO', 3)
            for conn in (tracker, witness):
                equal(conn.cmd('CLIENT', 'TRACKING', 'ON', 'NOLOOP'), b'OK', 'tracking armed')
            for attempt in range(8):
                key = f'notifyorder:noloop:{attempt}'
                equal(peer.driver.cmd('SET', key, 'v', 'PX', 100), b'OK', 'tracking seed')
                a = tracker.cmd('GET', key)
                b = witness.cmd('GET', key)
                due = peer.driver.cmd('PEXPIRETIME', key)
                if a == b == b'v' and due > 0:
                    break
                # Fresh connections too: failed arms may retain stale registrations.
                tracker.close(); witness.close()
                tracker = Conn(peer.host, peer.port, buffering=0, timeout=5)
                witness = Conn(peer.host, peer.port, buffering=0, timeout=5)
                for conn in (tracker, witness):
                    conn.cmd('HELLO', 3)
                    equal(conn.cmd('CLIENT', 'TRACKING', 'ON', 'NOLOOP'), b'OK', 'rearm tracker')
            else:
                raise AssertionError('tracking live registration window never opened')
            peer.quiesce()
            poll(lambda: peer.clock() > due + 2, 'tracking expiry deadline')
            equal(tracker.cmd('GET', key), None, 'self lazy GET')
            # The other NOLOOP client is a positive delivery witness; suppressing
            # all expiry invalidations cannot pass the self-suppression assertion.
            equal(witness.read(), [b'invalidate', [key.encode()]], 'other client invalidated')
            equal(tracker.cmd('PING'), b'PONG', 'NOLOOP self has no pending push')
            assert not select.select([tracker.sock], [], [], .05)[0], 'NOLOOP self invalidated'
            print('PASS lazy expiry CLIENT TRACKING NOLOOP target=' + str(peer.target), flush=True)
        finally:
            tracker.close(); witness.close()


def aof_case(peers, output):
    from aof_frames import read_frames
    import io
    keys = choose(peers[0], 'notifyorder:aof', 'A5')
    equal(shard_of(peers[0].admin, keys[0]), shard_of(peers[0].admin, keys[1]), 'local script shard')
    script = "redis.call('SET',KEYS[1],'one'); redis.call('SET',KEYS[2],'two'); return 2"
    results = []
    for peer in peers:
        equal(peer.admin.cmd('CONFIG', 'GET', 'appendonly'), [b'appendonly', b'yes'], 'AOF enabled')
        equal(peer.admin.cmd('CONFIG', 'GET', 'appendfsync'), [b'appendfsync', b'always'], 'durable reply')
        peer.configure('AKE')
        equal(peer.driver.cmd('EVAL', script, 2, *keys), 2, 'local script writes')
        equal(peer.collect(4), frames([('set', key) for key in keys]), 'script recorded notifications')
        live = peer.driver.cmd('MGET', *keys)
        equal(live, [b'one', b'two'], 'live script state')
        directory = Path(peer.admin.cmd('CONFIG', 'GET', 'dir')[1].decode())
        appenddir = peer.admin.cmd('CONFIG', 'GET', 'appenddirname')[1].decode()
        records = []
        if peer.target:
            paths = list((directory / appenddir).glob('*.incr.tomo'))
            assert paths, 'no target AOF increment'
            for path in paths:
                chunks, _size, truncated = read_frames(path)
                assert truncated is None, 'target AOF has incomplete frame after durable reply'
                for chunk in chunks:
                    records += [(kind, key.decode(), ticket) for kind, key, _size, ticket, _pos in chunk.records()]
            writes = [(key, ticket) for kind, key, ticket in records if kind == 5 and key in keys]
            tickets = {ticket for _key, ticket in writes}
            grouped = (len(writes) == 2 and {key for key, _ticket in writes} == set(keys)
                       and len(tickets) == 1 and 0 not in tickets
                       and any(kind == 7 and ticket in tickets for kind, _key, ticket in records)
                       and not any(kind in (1, 2) and key in keys for kind, key, _ticket in records))
        else:
            paths = list((directory / appenddir).glob('*.incr.aof'))
            assert paths, 'no oracle AOF increment'
            for path in paths:
                decoder = Conn.__new__(Conn)
                decoder.file = io.BytesIO(path.read_bytes())
                while decoder.file.tell() < len(decoder.file.getbuffer()):
                    records.append(decoder.read())
            last_flush = max(i for i, record in enumerate(records) if record == [b'FLUSHALL'])
            records = records[last_flush + 1:]
            wanted = [[b'MULTI'], [b'SET', keys[0].encode(), b'one'],
                      [b'SET', keys[1].encode(), b'two'], [b'EXEC']]
            grouped = records == wanted
        peer.configure('')
        equal(peer.admin.cmd('DEBUG', 'LOADAOF'), b'OK', 'AOF reload')
        recovered = peer.driver.cmd('MGET', *keys)
        result = dict(target=peer.target, keys=keys, records=repr(records), grouped=grouped,
                      live=repr(live), recovered=repr(recovered))
        results.append(result)
        print(json.dumps(result), flush=True)
    Path(output).write_text(json.dumps(results, indent=2) + '\n')
    assert results[1]['grouped'], 'Redis did not group script effects in MULTI/EXEC'
    equal(results[1]['recovered'], results[1]['live'], 'oracle reload')
    assert results[0]['grouped'], 'target lost local script grouped AOF record with notifications on'
    equal(results[0]['recovered'], results[0]['live'], 'target reload')
    equal(results[0]['recovered'], results[1]['recovered'], 'AOF reload differential')
    print('PASS local script notifications + grouped AOF + reload vs Redis', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    parser.add_argument('--oracle', nargs=2, required=True)
    parser.add_argument('--aof', type=Path, help='check local script AOF and write evidence')
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--engine', choices=('epoll', 'uring'), required=True)
    parser.add_argument('--atomic', type=int, choices=(0, 1), required=True)
    parser.add_argument('--read-local', type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    peers, failures = [], []
    try:
        peers.append(Peer(args.host, args.port, True,
                          (args.mode, args.engine, args.atomic, args.read_local)))
        peers.append(Peer(*args.oracle))
        if args.aof:
            aof_case(peers, args.aof)
            return 0
        for kind, count in [('C1', 8), ('C2', 2), ('C3', 4), ('C4', 4), ('C5', 1), ('C6', 1), ('C7', 1), ('C8', 1)]:
            for trial in range(count):
                try:
                    run_case(peers, kind, trial)
                except (AssertionError, OSError, EOFError) as error:
                    failures.append(f'{kind}/{trial}: {error}')
                    print('FAIL ' + failures[-1], flush=True)
        try:
            tracking_case(peers)
        except (AssertionError, OSError, EOFError) as error:
            failures.append('NOLOOP: ' + str(error))
            print('FAIL ' + failures[-1], flush=True)
    finally:
        for peer in peers:
            peer.close()
    print(f'notifyorder: {23-len(failures)} cases passed; {len(failures)} failures', flush=True)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
