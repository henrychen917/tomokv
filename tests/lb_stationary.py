#!/usr/bin/env python3
"""Stationary, balanced GET traffic must cause no LB moves after stabilization.

Every round sends one GET per shard on one connection per client-serving thread.
DEBUG LBSIGNALS proves owner coverage and operation conservation; INFO LB proves
both controllers are enabled and ticking. Gathers are diagnostic: the owner's
thrash definition is ownership moves. No skipped or shortened assertion window.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
import json
from pathlib import Path
import time

import _lib

MOTION = ('tomokv_keylb_bucket_moves', 'tomokv_keylb_client_moves')
TICKS = 'tomokv_keylb_ticks'
GATHERS = 'tomokv_keylb_bucket_gathers'
SETTLE_SECONDS = 12  # four current 3-second decisions before arming


def counters(conn):
    row = _lib.info(conn, 'LB')
    for name in ('tomokv_keylb_enabled', 'tomokv_clientlb_enabled'):
        if row.get(name) != '1':
            raise AssertionError('stationary LB requires both balancers enabled: ' + name)
    return {key: int(row[key]) for key in (*MOTION, TICKS, GATHERS)}


def unmoved(before, after):
    for key in MOTION:
        if before[key] != after[key]:
            raise AssertionError(f'stationary LB moved after stabilization: {key} {before[key]} -> {after[key]}')


def active(before, after, rounds):
    if not rounds or after[TICKS] <= before[TICKS]:
        raise AssertionError('stationary LB assertion window never opened: no rounds/ticks')


def checked_ops(before, after, rounds, clients, shards):
    # Sample only between completed rounds; the read-only observer contributes
    # at most a few DEBUG/INFO ops. Work conservation uses a fixed absolute
    # observer allowance, not a percentage that can conceal an inactive owner.
    old_shards = {s.sid: s.ops for s in before.shards}
    expected = rounds * clients
    for shard in after.shards:
        if not expected <= shard.ops - old_shards[shard.sid] <= expected + 16:
            raise AssertionError('stationary LB unequal shard traffic: ' + str(shard.sid))
    old_threads = {t.tid: t for t in before.threads}
    owners = Counter(s.owner for s in before.shards)
    if len(set(owners.values())) != 1:
        raise AssertionError('stationary LB owner geometry is not balanced')
    for thread in after.threads:
        delta = thread.ops - old_threads[thread.tid].ops
        wanted = rounds * shards if thread.role == 'io' else expected * owners[thread.tid]
        if thread.role == 'fused':
            wanted += rounds * shards  # parsing and owner execution share this signal
        if not wanted <= delta <= wanted + 16:
            raise AssertionError(f'stationary LB unequal thread traffic: t{thread.tid} {delta} expected {wanted}..{wanted + 16}')


def attempt(host, port, seconds, number):
    with ExitStack() as stack:
        admin = stack.enter_context(closing(_lib.Conn(host, port, timeout=10)))
        snap = _lib.lbsignals(admin)
        tids = {t.tid for t in snap.threads if t.role in ('io', 'fused')}
        if len(snap.shards) != 16 or len(snap.threads) != 8:
            raise AssertionError('stationary LB requires the gate 8-thread/16-shard geometry')
        if _lib.info(admin, 'server').get('flip_auto') != '0':
            raise AssertionError('stationary LB requires flip-auto 0')
        # Route discovery uses an acknowledged IO-local CLIENT ID batch and actual thread-op
        # deltas, without a new server hook or a guessed SO_REUSEPORT assignment.
        clients = {}
        for _ in range(256):
            conn = _lib.Conn(host, port, timeout=10)
            before = _lib.lbsignals(admin)
            conn.raw(_lib.encode('CLIENT', 'ID') * 64)
            if any(not isinstance(conn.read(), int) for _ in range(64)):
                conn.close()
                raise AssertionError('stationary LB connection probe failed')
            old = {t.tid: t.ops for t in before.threads}
            new = _lib.lbsignals(admin)
            match = [t.tid for t in new.threads if t.tid in tids and t.ops - old[t.tid] >= 64]
            if len(match) == 1 and match[0] not in clients:
                clients[match[0]] = stack.enter_context(closing(conn))
            else:
                conn.close()
            if set(clients) == tids:
                break
        if set(clients) != tids:
            return None, 'could not arm one connection on each IO owner'
        keys = {}
        for i in range(8192):
            key = f'lb-hold:{number}:{i:06}'
            keys.setdefault(_lib.shard_of(admin, key), key)
            if len(keys) == 16:
                break
        if len(keys) != 16:
            raise AssertionError('stationary LB keyspace did not cover all shards')
        for key in keys.values():
            admin.must('SET', key, b'x' * 128)
        stack.callback(lambda: admin.must('DEL', *keys.values()))
        request = b''.join(_lib.encode('GET', keys[sid]) for sid in sorted(keys))
        before = counters(admin)
        initial = before
        snapshot = _lib.lbsignals(admin)
        quiet_since = time.monotonic()
        deadline = quiet_since + 60
        sample_at = quiet_since + 1
        baseline = None
        rounds = 0
        hold_rounds = 0
        samples = []
        while time.monotonic() < deadline:
            start = time.monotonic()
            for conn in clients.values(): conn.raw(request)
            for conn in clients.values():
                for _ in keys:
                    if conn.read() != b'x' * 128:
                        raise AssertionError('stationary LB reply corruption')
            rounds += 1
            if baseline is not None: hold_rounds += 1
            now = time.monotonic()
            if now >= sample_at:
                after = counters(admin)
                current = _lib.lbsignals(admin)
                try:
                    checked_ops(snapshot, current, rounds, len(clients), len(keys))
                except AssertionError as error:
                    if baseline is not None:
                        raise
                    return None, str(error)
                samples.append(dict(elapsed=now - start, counters=after, rounds=rounds))
                if baseline is not None:
                    unmoved(baseline, after)  # a single move fails immediately
                elif any(after[k] != before[k] for k in MOTION):
                    quiet_since = now
                elif now - quiet_since >= SETTLE_SECONDS:
                    active(initial, after, rounds)
                    baseline = after
                    deadline = now + seconds  # a full hold starts HERE
                    print(f'LB stationary window armed: attempt {number}, hold {seconds}s', flush=True)
                before, snapshot, rounds = after, current, 0
                sample_at = now + 1
            time.sleep(max(0, .01 - (time.monotonic() - start)))
        if baseline is None:
            return None, 'stabilization window never opened'
        after = counters(admin)
        unmoved(baseline, after)
        active(baseline, after, hold_rounds)
        checked_ops(snapshot, _lib.lbsignals(admin), rounds, len(clients), len(keys))
        return dict(before=baseline, after=after, rounds=hold_rounds, seconds=seconds,
                    samples=samples, gather_delta=after[GATHERS] - baseline[GATHERS]), None


def self_test():
    before = dict(zip((*MOTION, TICKS, GATHERS), (4, 7, 20, 9)))
    unmoved(before, dict(before, **{TICKS: 50, GATHERS: 10}))
    active(before, dict(before, **{TICKS: 50}), 100)
    for key in MOTION:
        try:
            unmoved(before, dict(before, **{key: before[key] + 1}))
        except AssertionError as error:
            assert 'moved after stabilization' in str(error)
        else: raise AssertionError('move negative control passed')
    for after, rounds in ((before, 100), (dict(before, **{TICKS: 50}), 0)):
        try: active(before, after, rounds)
        except AssertionError as error:
            assert 'window never opened' in str(error)
        else: raise AssertionError('inactive-window negative control passed')
    print('PASS stationary LB move and unentered-window controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.seconds < 30: parser.error('hold must span at least 30 seconds')
        failures = []
        for number in range(1, 4):
            result, error = attempt(args.host, args.port, args.seconds, number)
            if result is not None:
                args.output.write_text(json.dumps(result, indent=2) + '\n')
                print('PASS stationary LB: no key/client moves; gathers reported separately')
                break
            failures.append(error)
            print(f'LB fresh-state re-arm {number}/3: {error}', flush=True)
        else:
            raise AssertionError('stationary LB assertion window never opened after three fresh-state re-arms: ' + repr(failures))
