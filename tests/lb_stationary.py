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
    if {s.sid for s in after.shards} != set(old_shards):
        raise AssertionError('stationary LB shard inventory changed')
    expected = rounds * clients
    for shard in after.shards:
        if not expected <= shard.ops - old_shards[shard.sid] <= expected + 16:
            raise AssertionError('stationary LB unequal shard traffic: ' + str(shard.sid))
    old_threads = {t.tid: t for t in before.threads}
    if {t.tid for t in after.threads} != set(old_threads):
        raise AssertionError('stationary LB thread inventory changed')
    owners = Counter(s.owner for s in before.shards)
    if len(set(owners.values())) != 1:
        raise AssertionError('stationary LB owner geometry is not balanced')
    by_role = {}
    for thread in after.threads:
        delta = thread.ops - old_threads[thread.tid].ops
        minimum = rounds * shards if thread.role in ('io', 'fused') else expected * owners[thread.tid]
        if delta < minimum:
            raise AssertionError(f'stationary LB inactive thread: t{thread.tid} {delta} < {minimum}')
        by_role.setdefault(thread.role, []).append(delta)
    # The fused counter combines parsing and owner work; compare like roles
    # directly instead of assuming an unmeasured fused accounting multiplier.
    for role, deltas in by_role.items():
        if max(deltas) - min(deltas) > 16:
            raise AssertionError(f'stationary LB unequal thread traffic: {role} {deltas}')


def client_threads(snap, info):
    """Cross-check the actual serving set, as lbsignals.py does for each mode."""
    mode = snap.derived['thread_mode']
    role = {'1s': 'fused', '2s': 'io'}[mode]
    tids = {t.tid for t in snap.threads if t.role == role}
    count = len(tids)
    count_field = 'lb_fused_threads' if mode == '1s' else 'lb_io_threads'
    if not count or not (int(snap.derived['client_threads']) ==
                         int(snap.rollups[role]['threads']) ==
                         int(info[count_field]) == count):
        raise AssertionError('stationary LB client-owner inventory disagrees with INFO/LBSIGNALS')
    return tids


def probe_owner(admin, conn, tids, request, commands):
    # CLIENT ID is local and does not charge LoopSignals.ops. Ordinary GETs do.
    # Cover every shard equally: in 1s each shard owner executes only its share,
    # while the connection's IO owner parses the WHOLE batch (also in 2s).
    before = {t.tid: t.ops for t in _lib.lbsignals(admin).threads}
    conn.raw(request)
    for _ in range(commands):
        if conn.read() != b'x' * 128:
            raise AssertionError('stationary LB connection probe reply corruption')

    def owner():
        current = _lib.lbsignals(admin)
        matches = [t.tid for t in current.threads
                   if t.tid in tids and t.ops - before[t.tid] >= commands]
        if len(matches) > 1:
            raise AssertionError('stationary LB connection probe has multiple IO owners')
        return matches or None  # tid 0 is a valid owner, not a false result

    matches = _lib.wait_until(owner, 1, interval=.01)
    return matches[0] if matches else None


def attempt(host, port, seconds, number):
    with ExitStack() as stack:
        admin = stack.enter_context(closing(_lib.Conn(host, port, timeout=10)))
        snap = _lib.lbsignals(admin)
        tids = client_threads(snap, _lib.info(admin, 'LB'))
        if len(snap.shards) != 16 or len(snap.threads) != 8:
            raise AssertionError('stationary LB requires the gate 8-thread/16-shard geometry')
        if _lib.info(admin, 'server').get('flip_auto') != '0':
            raise AssertionError('stationary LB requires flip-auto 0')
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
        clients = {}
        for _ in range(256):
            conn = stack.enter_context(closing(_lib.Conn(host, port, timeout=10)))
            tid = probe_owner(admin, conn, tids, request * 4, len(keys) * 4)
            if tid is None:
                return None, 'connection probe never charged its IO owner'
            if tid not in clients:
                clients[tid] = conn
            else:
                conn.close()
            if set(clients) == tids:
                break
        if set(clients) != tids:
            return None, ('could not arm one connection on each actual IO owner: '
                          f'wanted={sorted(tids)}, armed={sorted(clients)}')
        print(f'LB stationary owners: mode={snap.derived["thread_mode"]} '
              f'clients={sorted(clients)} shards={len(keys)}', flush=True)
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
                if baseline is not None:
                    unmoved(baseline, after)  # a single move fails immediately
                try:
                    checked_ops(snapshot, current, rounds, len(clients), len(keys))
                except AssertionError as error:
                    if baseline is not None:
                        raise
                    return None, str(error)
                samples.append(dict(elapsed=now - start, counters=after, rounds=rounds))
                if baseline is not None:
                    pass
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


def run(host, port, seconds):
    failures = []
    for number in range(1, 4):
        result, error = attempt(host, port, seconds, number)
        if result is not None:
            return result
        failures.append(error)
        print(f'LB fresh-state re-arm {number}/3: {error}', flush=True)
    raise AssertionError('stationary LB assertion window never opened after three fresh-state re-arms: '
                         + repr(failures))


def self_test():
    from types import SimpleNamespace as N
    from unittest.mock import patch
    # Real gate shapes: 8 fused client owners, or 6 IO + 2 executor owners.
    # Give noncontiguous IDs to make accidental range(count) assumptions fail.
    request = b''.join(_lib.encode('GET', f'fixture:{sid}') for sid in range(16)) * 4
    for mode, tids, owners in (('1s', [2, 4, 6, 8, 10, 12, 14, 16], 8),
                               ('2s', [2, 4, 6, 8, 10, 12], 2)):
        role = 'fused' if mode == '1s' else 'io'
        base = [N(tid=tid, role=role, ops=0) for tid in tids]
        if mode == '2s': base += [N(tid=20 + i, role='ex', ops=0) for i in range(owners)]
        snap = N(threads=base, derived=dict(thread_mode=mode, client_threads=str(len(tids))),
                 rollups={role: dict(threads=len(tids))})
        field = 'lb_fused_threads' if mode == '1s' else 'lb_io_threads'
        assert client_threads(snap, {field: str(len(tids))}) == set(tids)
        try: client_threads(snap, {field: str(len(tids) + 1)})
        except AssertionError as error:
            assert 'inventory disagrees' in str(error)
        else: raise AssertionError('wrong owner-count negative control passed')
        for tid in tids:
            after = N(threads=[N(tid=t.tid, ops=(64 if t.tid == tid else 0) +
                                  (64 // owners if t.role in ('fused', 'ex') else 0))
                               for t in base])
            conn = N(raw=lambda data: None, read=lambda: b'x' * 128)
            with patch.object(_lib, 'lbsignals', side_effect=[snap, snap, after]):
                assert probe_owner(None, conn, set(tids), request, 64) == tid
        # Model the old local CLIENT ID probe: replies arrive but no ops charge.
        # A missing window must stay absent, even with all owners in the schema.
        with patch.object(_lib, 'lbsignals', return_value=snap), \
             patch.object(_lib, 'wait_until', side_effect=lambda predicate, *a, **kw: predicate()):
            assert probe_owner(None, conn, set(tids), request, 64) is None
    with patch(__name__ + '.attempt', return_value=(None, 'unarmed owner')) as attempts:
        try: run('unused', 0, 30)
        except AssertionError as error:
            assert 'never opened after three fresh-state re-arms' in str(error)
        else: raise AssertionError('unarmed attempts silently passed')
        assert [call.args[-1] for call in attempts.call_args_list] == [1, 2, 3]
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
    before_ops = N(shards=[N(sid=i, owner=i % 2, ops=0) for i in range(16)],
                   threads=[N(tid=i, role='fused', ops=0) for i in range(2)])
    after_ops = N(shards=[N(sid=i, owner=i % 2, ops=20) for i in range(16)],
                  threads=[N(tid=i, role='fused', ops=320) for i in range(2)])
    checked_ops(before_ops, after_ops, 10, 2, 16)
    after_ops.threads[1].ops = 0
    try: checked_ops(before_ops, after_ops, 10, 2, 16)
    except AssertionError as error:
        assert 'inactive thread' in str(error)
    else: raise AssertionError('inactive-owner negative control passed')
    after_ops.threads[1].ops = 320
    after_ops.shards[0].ops = 0
    try: checked_ops(before_ops, after_ops, 10, 2, 16)
    except AssertionError as error:
        assert 'unequal shard traffic' in str(error)
    else: raise AssertionError('inactive-shard negative control passed')
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
        result = run(args.host, args.port, args.seconds)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print('PASS stationary LB: no key/client moves; gathers reported separately')
