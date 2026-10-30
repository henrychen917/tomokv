#!/usr/bin/env python3
"""FLUSHALL completion RTT and resident-memory reclamation, ABBA or ABCCBA.

Default matrix: 0/1M/10M DB-0 keys, 16 bytes each, 64-byte values, no TTL;
1s/read-local=1 and 2s/read-local=0; atomic 0/1; databases 1/16; SYNC/ASYNC.
--trials/--empty-trials are MINIMUM observations per arm and cell across all
blocks, rounded up to equal per-visit counts. Every seed is outside the timer.
RSS is /proc/<owned-pid>/status VmRSS at the three specified boundaries; an
optional delayed sample is separate from command completion. No MEMORY PURGE.
"""
import math
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

import flushmerit as fm


def cells(args):
    populations = [int(x) for x in args.populations.split(',')]
    fm.require(populations and min(populations) >= 0 and len(set(populations)) == len(populations), 'invalid populations')
    fm.require(args.trials > 0 and args.empty_trials > 0 and args.rss_settle >= 0, 'invalid repetitions/settle')
    fm.require(args.smoke or (args.trials >= 100 and args.empty_trials >= 1000),
               'merit requires >=100 nonempty and >=1000 empty observations per arm/cell')
    return [dict(name=f'{mode}-a{atomic}-db{db}-{flush}-n{population}', mode=mode, atomic=int(atomic),
                 databases=int(db), read_local=int(mode == '1s'), flush=flush, population=population)
            for mode in fm.choices(args.modes, ('1s', '2s'))
            for atomic in fm.choices(args.atomics, ('0', '1'))
            for db in fm.choices(args.databases, ('1', '16'))
            for flush in fm.choices(args.flushes, ('SYNC', 'ASYNC')) for population in populations]


def observe(conn, pid, seed, flush, settle):
    fm.check_size(conn, 0)
    rss_before = fm.rss(pid)
    seed_start = time.monotonic_ns()
    seeded = seed.replay(conn)
    seed_ns = time.monotonic_ns() - seed_start
    # This independent, immediate DBSIZE guard is deliberately outside the timer.
    fm.check_size(conn, seed.count)
    before = fm.info(conn)
    rss_seed = fm.rss(pid)
    started = time.monotonic_ns()
    reply = conn.cmd('FLUSHALL', flush)
    latency = time.monotonic_ns() - started
    rss_flush = fm.rss(pid)
    fm.ok(reply)
    fm.check_size(conn, 0)
    fm.check_keyspace(conn, 0)
    after = fm.info(conn)
    row = dict(latency_ns=latency, seeded=seeded, seed_ns=seed_ns,
               rss_before_seed_bytes=rss_before, rss_after_seed_bytes=rss_seed,
               rss_after_flush_bytes=rss_flush, rss_reclaimed_bytes=rss_seed - rss_flush,
               info_before={key: before.get(key) for key in fm.COUNTERS},
               info_after={key: after.get(key) for key in fm.COUNTERS}, info_delta=fm.deltas(before, after))
    if settle:
        time.sleep(settle)
        row['rss_settled_bytes'] = fm.rss(pid)
        row['rss_settle_seconds'] = settle
    return row


def run(args, cell, binary, folder, _calibration):
    target = args.empty_trials if cell['population'] == 0 else args.trials
    repeats = math.ceil(target / (2 * args.blocks))
    observations = []
    with fm.server(args, cell, binary, folder) as (process, conn):
        fm.check_size(conn, 0)
        seed = fm.Seed(conn, cell['population'], folder)
        try:
            for index in range(repeats):
                row = observe(conn, process.pid, seed, cell['flush'], args.rss_settle)
                row['index'] = index
                observations.append(row)
                # Keep every completed observation even on a later failure.
                fm.save(folder / 'observations.json', observations)
        finally:
            seed.close()
    return dict(valid=True, observations_file=str(folder / 'observations.json'),
                latency=fm.distribution([row['latency_ns'] for row in observations]),
                repetitions=repeats, per_arm_cell_total=repeats * 2 * args.blocks,
                rss={key: dict(min=min(row[key] for row in observations),
                               max=max(row[key] for row in observations)) for key in
                     ('rss_before_seed_bytes', 'rss_after_seed_bytes', 'rss_after_flush_bytes', 'rss_reclaimed_bytes')},
                counters={key: None if observations[0]['info_delta'][key] is None else
                          sum(row['info_delta'][key] for row in observations) for key in fm.COUNTERS})


def selftest():
    fm.base_selftest()
    conn, seed = Mock(), Mock(count=2)
    seed.replay.return_value = 2
    def reply(*args):
        if args[0] == 'FLUSHALL':
            return b'OK'
        if args == ('INFO', 'keyspace'):
            return b'# Keyspace\r\n'
        if args[0] == 'INFO':
            return b'atomic_flush_units:2\r\n'
        return 0
    conn.cmd.side_effect = reply
    with patch.object(fm, 'check_size'), patch.object(fm, 'rss', side_effect=[100, 300, 120]), \
            patch.object(time, 'monotonic_ns', side_effect=[10, 20, 30, 80]):
        row = observe(conn, 123, seed, 'SYNC', 0)
    assert row['latency_ns'] == 50 and row['seed_ns'] == 10 and row['rss_reclaimed_bytes'] == 180
    assert row['info_delta']['atomic_flush_units'] == 0
    # Both seed and post-flush population mismatches must be fatal, not retried/skipped.
    for sizes in ([1], [0, 1], [0, 2, 1]):
        mock = Mock()
        sizes = iter(sizes)
        mock.cmd.side_effect = lambda *a: next(sizes) if a[0] == 'DBSIZE' else reply(*a)
        with patch.object(fm, 'rss', return_value=100):
            fm.rejects(lambda: observe(mock, 123, seed, 'ASYNC', 0))
    line, valid = fm.summary('flush_latency', [{'valid': True}] * 4, 4, True)
    assert valid and line.startswith('flush_latency: status=VALID kind=SMOKE_ONLY') and '\n' not in line
    print('flush_latency selftest: PASS')
    return 0


def main():
    p = fm.common_parser(__doc__)
    p.add_argument('--populations', default='0,1000000,10000000')
    p.add_argument('--trials', type=int, default=100)
    p.add_argument('--empty-trials', type=int, default=1000)
    p.add_argument('--rss-settle', type=float, default=0,
                   help='optional additional RSS sample seconds after reply, outside latency timer')
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return fm.campaign(args, 'flush_latency', cells(args), run)


if __name__ == '__main__':
    sys.exit(main())
