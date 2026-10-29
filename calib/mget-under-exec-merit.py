#!/usr/bin/env python3
"""Atomic-1 MGET under EXEC load, fresh-server ABBA / optional ABCCBA.

64 reader connections at pipeline 8; eight writers, one MULTI/SET x8/EXEC in
flight each, on eight fixed 16-byte keys occupying shards 0,2,...,14. Each
transaction writes the same unique 64-byte token to all keys. Every MGET must
return eight identical valid tokens; read tokens must belong to acknowledged
transactions after the writers drain. Every run requires LIVE atomic_entries
samples and a positive atomic_predecessor_reads delta. No debug holds or hooks.
Both modes, databases 1/16, read-local 0, fixed offered reader/writer rates
calibrated against all arms. --profile retains the existing gate's approximate
server cycles/command, instructions/command and IPC in cpu-profile.json.
"""
import json
import math
import sys
import time
from unittest.mock import Mock

import flushmerit as fm

INITIAL = b'initial'.ljust(64, b'.')


def cells(args):
    fm.check_pacing(args)
    fm.require(args.atomics == '1', 'this instrument requires atomic 1')
    return [dict(name=f'{mode}-a1-db{db}-mget-exec', mode=mode, atomic=1, databases=int(db), read_local=0)
            for mode in fm.choices(args.modes, ('1s', '2s'))
            for db in fm.choices(args.databases, ('1', '16'))]


def token(writer, seq):
    return f't{writer}:{seq:016d}'.encode().ljust(64, b'.')


def validate_read(reply, observed):
    fm.require(isinstance(reply, list) and len(reply) == 8, 'MGET reply is not eight values')
    first = reply[0]
    fm.require(isinstance(first, bytes) and len(first) == 64 and all(v == first for v in reply),
               'torn/missing/malformed MGET values')
    if first == INITIAL:
        return
    try:
        owner, seq = first.rstrip(b'.').split(b':')
        writer = int(owner[1:])
        sequence = int(seq)
        fm.require(0 <= writer < 8 and sequence > 0 and first == token(writer, sequence), 'invalid writer token')
    except (ValueError, TypeError):
        raise fm.Invalid('malformed transaction token') from None
    observed[str(writer)] = max(observed.get(str(writer), 0), sequence)


def validate_exec(conn):
    fm.require([conn.read() for _ in range(9)] == [b'OK'] + [b'QUEUED'] * 8, 'bad MULTI/SET queue replies')
    fm.require(conn.read() == [b'OK'] * 8, 'EXEC was aborted or returned a wrong SET result')


def witnesses(window):
    # Samples from the active window only; a baseline or post-drain sample is not evidence.
    active = [row for row in window['samples'] if 0 <= row['t'] < window['offered_seconds']]
    fm.require(active and any(row['atomic_entries'] > int(window['info_before']['atomic_entries']) and
                              row['atomic_pending_entries'] > 0 for row in active),
               'no live atomic entries sampled during the offered window')
    fm.require((window['info_delta']['atomic_predecessor_reads'] or 0) > 0,
               'no predecessor reads; unopened mechanism window')
    return dict(live_samples=sum(row['atomic_pending_entries'] > 0 for row in active),
                peak_pending_entries=max(row['atomic_pending_entries'] for row in active),
                peak_entries_counter=max(row['atomic_entries'] for row in active), samples=len(active),
                predecessor_reads=window['info_delta']['atomic_predecessor_reads'])


def final_data(conn, keys, readers, writers):
    fm.check_size(conn, 8)
    fm.check_keyspace(conn, 8)
    observed = {}
    validate_read(conn.cmd('MGET', *keys), observed)
    for reader in readers:
        for writer, sequence in reader['observed'].items():
            observed[writer] = max(observed.get(writer, 0), sequence)
    for writer, sequence in observed.items():
        fm.require(sequence <= writers[int(writer)]['completed'], 'read an unacknowledged transaction token')
    fm.require(all(writer['completed'] > 0 for writer in writers), 'inactive EXEC writer')
    return observed


def run(args, cell, binary, folder, offered):
    with fm.server(args, cell, binary, folder) as (process, conn):
        all_keys, all_routes = fm.pick_keys(conn)
        keys, geometry = all_keys[::2], all_routes[::2]
        fm.require([row[0] for row in geometry] == list(range(0, 16, 2)), 'eight-key shard coverage changed')
        fm.ok(conn.cmd('MSET', *(part for key in keys for part in (key, INITIAL))))
        fm.check_size(conn, 8)
        packet = fm.encode('MGET', *keys) * 8
        def worker(c, index, epoch, stop):
            reader = index < 64
            wid = index if reader else index - 64
            conns, batch = (64, 8) if reader else (8, 1)
            metric = 'readers' if reader else 'writers'
            rate = offered[metric] / conns / batch if offered else None
            batches = completed = within = 0
            observed, lags = {}, []
            end = epoch + args.secs
            expected_batches = max(0, math.ceil(args.secs * rate - wid / conns - 1e-9)) if rate else None
            while not stop.is_set():
                when = epoch + (batches + wid / conns) / rate if rate else time.monotonic()
                if (rate and batches >= expected_batches) or (not rate and when >= end):
                    break
                fm.sleep_until(when if rate else epoch)
                started = time.monotonic()
                if reader:
                    c.sock.sendall(packet)
                    for _ in range(8):
                        validate_read(c.read(), observed)
                        within += time.monotonic() <= end
                else:
                    data = token(wid, batches + 1)
                    transaction = fm.encode('MULTI') + b''.join(fm.encode('SET', key, data) for key in keys) + fm.encode('EXEC')
                    c.sock.sendall(transaction)
                    validate_exec(c)
                    within += time.monotonic() <= end
                completed += batch
                batches += 1
                lags.append(max(0, int((started - when) * 1e9)) if rate else 0)
            return dict(kind=metric, completed=completed, scheduled=expected_batches * batch if rate else completed,
                        within_window=within, elapsed=time.monotonic() - epoch, observed=observed, lag_ns=lags,
                        commands=completed if reader else completed * 10)
        window = fm.load_window(args, process, conn, folder, 72, worker, sample=True,
                                profile=args.profile and offered is not None)
        readers, writers = window['workers'][:64], window['workers'][64:]
        if offered:
            fm.offered_valid(window['workers'], args.secs, args.max_lag_ms)
        fm.require(all(row['completed'] > 0 for row in readers), 'inactive MGET reader')
        witnessed = witnesses(window)
        observed = final_data(conn, keys, readers, writers)
        elapsed = max(args.secs, max(row['elapsed'] for row in window['workers']))
        result = dict(valid=True, offered=offered, elapsed=elapsed,
            completed=dict(readers=sum(r['completed'] for r in readers), writers=sum(r['completed'] for r in writers)),
            rates=dict(readers=sum(r['completed'] for r in readers) / elapsed,
                       writers=sum(r['completed'] for r in writers) / elapsed),
            rate_units=dict(readers='MGET commands/s (eight values each)', writers='committed transactions/s (eight SETs each)'),
            witness=witnessed, observed_tokens=observed, info_delta=window['info_delta'],
            keys=[key.decode() for key in keys], geometry=geometry,
            schedule_lag=fm.distribution([x for row in window['workers'] for x in row['lag_ns']]))
        if args.profile and offered is not None:
            profile = json.loads((folder / 'cpu-profile.json').read_text())
            fm.require(profile['status'] == 'COMPLETE', 'incomplete server profile')
            result['cpu_profile'] = profile['derived']
            result['cpu_profile_scope'] = 'approximate combined server / RESP command, includes both workloads and interval overhang'
    return result


def calibrate(args, arms, selected):
    return fm.calibration(args, arms, selected, run, ('readers', 'writers'))


def selftest():
    fm.base_selftest()
    c = Mock()
    c.read.side_effect = [b'OK'] + [b'QUEUED'] * 8 + [[b'OK'] * 8]
    validate_exec(c)
    for broken in ([b'OK'] + [b'QUEUED'] * 8 + [None], [b'OK'] * 10):
        c.read.side_effect = broken
        fm.rejects(lambda: validate_exec(c))
    observed = {}
    validate_read([token(2, 5)] * 8, observed)
    assert observed == {'2': 5}
    for broken in ([None] * 8, [token(1, 1)] * 7, [token(1, 1)] * 7 + [token(1, 2)],
                   [b'x' * 64] * 8, [token(8, 1)] * 8):
        fm.rejects(lambda: validate_read(broken, {}))
    window = dict(samples=[dict(t=.5, atomic_entries=2, atomic_pending_entries=1)], offered_seconds=1,
                  info_before=dict(atomic_entries='0'),
                  info_delta=dict(atomic_predecessor_reads=5))
    assert witnesses(window)['live_samples'] == 1
    for poison in (dict(samples=[]), dict(samples=[dict(t=-.1, atomic_entries=10)]),
                   dict(samples=[dict(t=.5, atomic_entries=0, atomic_pending_entries=0)]),
                   dict(samples=[dict(t=.5, atomic_entries=20, atomic_pending_entries=0)]), dict(info_delta=dict(atomic_predecessor_reads=0))):
        fm.rejects(lambda: witnesses(dict(window, **poison)))
    line, valid = fm.summary('mget_under_exec', [{'valid': True}] * 4, 4)
    assert valid and line.startswith('mget_under_exec: status=VALID') and '\n' not in line
    print('mget_under_exec selftest: PASS')
    return 0


def main():
    p = fm.common_parser(__doc__)
    p.set_defaults(atomics='1')
    fm.pacing_options(p)
    p.add_argument('--profile', action='store_true', help='require grouped per-server-thread PMCs using tests/abba_profile.py')
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return fm.campaign(args, 'mget_under_exec', cells(args), run, calibrate)


if __name__ == '__main__':
    sys.exit(main())
