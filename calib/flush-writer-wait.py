#!/usr/bin/env python3
"""SET completion RTT upper bound under 10 Hz FLUSHALL, never pure claim wait.

16 writer connections, pipeline 1. same-key: all writers cycle the SAME 16
shard-spanning keys in the same order. disjoint-key: writer i owns key/shard i.
no-flush: disjoint-key schedule without flushes. FLUSHALL covers ALL keys in
either case; disjoint-key means disjoint writers, not disjoint from FLUSHALL.

Each arm/cell is calibrated, then the global minimum achieved SET rate times
--load-fraction is verified and frozen across ALL schedules, arms and blocks.
Scheduled-send lag and scheduled-to-completion latency are retained alongside
RTT to expose load-generator delay/coordinated omission. No dropped deadlines.
Optional --population seeds background keys once per boot; the first flush is
populated, subsequent flush sizes are observed, never described as replenished.
"""
import math
import sys
import time
from unittest.mock import Mock

import flushmerit as fm


def cells(args):
    fm.check_pacing(args)
    fm.require(args.population >= 0, 'negative population')
    schedules = fm.choices(args.schedules, ('same-key', 'disjoint-key', 'no-flush'))
    return [dict(name=f'{mode}-a{atomic}-db{db}-{flush}-{schedule}', mode=mode, atomic=int(atomic),
                 databases=int(db), read_local=int(mode == '1s'), flush=flush, schedule=schedule)
            for mode in fm.choices(args.modes, ('1s', '2s'))
            for atomic in fm.choices(args.atomics, ('0', '1'))
            for db in fm.choices(args.databases, ('1', '16'))
            for flush in fm.choices(args.flushes, ('SYNC', 'ASYNC')) for schedule in schedules]


def value(writer, seq):
    return f'w{writer:02d}:{seq:016d}'.encode().ljust(64, b'.')


def final_data(conn, keys, rows, flushes, population):
    actual = conn.cmd('MGET', *keys)
    fm.require(isinstance(actual, list) and len(actual) == 16, 'bad final MGET shape')
    last_flush = flushes[-1] if flushes else None
    for sid, observed in enumerate(actual):
        events = []
        for row in rows:
            event = row['last'].get(str(sid))
            if event:
                events.append((event['start'], event['end'], value(row['worker'], event['seq'])))
        if last_flush:
            events.append((last_flush['start'], last_flush['end'], None))
        fm.require(events, f'key {sid} was never exercised')
        # A final event must be maximal in the externally observable happens-before
        # order. Overlapping operations may linearize either way, including FLUSH.
        permitted = {v for start, end, v in events if not any(other_start > end for other_start, _, _ in events)}
        fm.require(observed in permitted, f'final value on shard {sid} not an acknowledged maximal write/flush')
    fm.check_size(conn, sum(v is not None for v in actual) + (0 if flushes else population))
    fm.check_keyspace(conn, sum(v is not None for v in actual) + (0 if flushes else population))
    return [v.decode() if v is not None else None for v in actual]


def flusher(conn, epoch, secs, stop, flush, pid):
    rows, lag = [], []
    index = 0
    while (when := epoch + .05 + index / 10) < epoch + secs and not stop.is_set():
        fm.sleep_until(when)
        population = conn.cmd('DBSIZE')
        rss_before = fm.rss(pid)
        started = time.monotonic()
        reply = conn.cmd('FLUSHALL', flush)
        ended = time.monotonic()
        fm.ok(reply)
        lag.append(max(0, int((started - when) * 1e9)))
        rows.append(dict(index=index, scheduled=when, start=started, end=ended,
                         latency_ns=int((ended - started) * 1e9), population_before=population,
                         rss_before_bytes=rss_before, rss_after_bytes=fm.rss(pid)))
        index += 1
    expected = max(0, math.ceil((secs - .05) * 10 - 1e-9))
    fm.require(len(rows) == expected and expected > 0, 'missed 10 Hz FLUSHALL event')
    fm.require(max(lag) < 100_000_000, 'FLUSHALL could not sustain 10 Hz; a complete period was missed')
    return dict(events=rows, lag_ns=lag, commands=len(rows), completed=len(rows))


def run(args, cell, binary, folder, offered):
    with fm.server(args, cell, binary, folder) as (process, conn):
        keys, geometry = fm.pick_keys(conn)
        seed = fm.Seed(conn, args.population, folder)
        try:
            seed.replay(conn)
        finally:
            seed.close()
        # Writer keys begin absent, separate from the optional background seed.
        def worker(c, index, epoch, stop):
            if index == 16:
                return flusher(c, epoch, args.secs, stop, cell['flush'], process.pid)
            rate = offered['sets'] / 16 if offered else None
            seq, within, rtts, lags, responses, last = 0, 0, [], [], [], {}
            end = epoch + args.secs
            expected = max(0, math.ceil(args.secs * rate - index / 16 - 1e-9)) if rate else None
            while not stop.is_set():
                when = epoch + (seq + index / 16) / rate if rate else time.monotonic()
                if (rate and seq >= expected) or (not rate and when >= end):
                    break
                fm.sleep_until(when if rate else epoch)
                sid = seq % 16 if cell['schedule'] == 'same-key' else index
                seq += 1
                started = time.monotonic()
                fm.ok(c.cmd('SET', keys[sid], value(index, seq)))
                ended = time.monotonic()
                within += ended <= end
                rtts.append(int((ended - started) * 1e9))
                lags.append(max(0, int((started - when) * 1e9)) if rate else 0)
                responses.append(max(0, int((ended - when) * 1e9)) if rate else rtts[-1])
                last[str(sid)] = dict(seq=seq, start=started, end=ended)
            return dict(completed=seq, scheduled=expected if rate else seq, within_window=within,
                        commands=seq, elapsed=time.monotonic() - epoch, rtt_ns=rtts,
                        lag_ns=lags, response_ns=responses, last=last)
        window = fm.load_window(args, process, conn, folder, 16 + (cell['schedule'] != 'no-flush'), worker)
        rows = window['workers'][:16]
        events = window['workers'][16]['events'] if len(window['workers']) > 16 else []
        if offered:
            fm.offered_valid(rows, args.secs, args.max_lag_ms)
        fm.require(all(row['completed'] > 0 for row in rows), 'inactive SET writer')
        final = final_data(conn, keys, rows, events, args.population)
        total = sum(row['completed'] for row in rows)
        # Count all drained completions in the measured elapsed client interval.
        elapsed = max(args.secs, max(row['elapsed'] for row in rows))
        result = dict(valid=True, offered=offered, rates=dict(sets=total / elapsed),
             completed=total, elapsed=elapsed, keys=[k.decode() for k in keys], geometry=geometry,
             final=final, initial_population=args.population,
             latency_label='client RTT upper bound on claim wait; not pure claim wait',
             claim_wait_duration_histogram=None,
             rtt=fm.distribution([x for row in rows for x in row['rtt_ns']]),
             scheduled_response=fm.distribution([x for row in rows for x in row['response_ns']]),
             schedule_lag=fm.distribution([x for row in rows for x in row['lag_ns']]),
             info_delta=window['info_delta'],
             claim_wait_counters={k: window['info_delta'][k] for k in fm.WAIT_COUNTERS},
             flush_count=len(events), flush_events=events,
             flush_latency=fm.distribution([event['latency_ns'] for event in events]) if events else None)
    return result


def calibrate(args, arms, selected):
    return fm.calibration(args, arms, selected, run, ('sets',))


def selftest():
    fm.base_selftest()
    # Exact final state: overlapping writes may win, a definitely earlier one may not.
    keys = [str(i).encode() for i in range(16)]
    rows = [dict(worker=i, last={str(i): dict(seq=1, start=2, end=3)}) for i in range(16)]
    c = Mock()
    actual = [value(i, 1) for i in range(16)]
    def reply(*args):
        return actual if args[0] == 'MGET' else 16 if args[0] == 'DBSIZE' else b'db0:keys=16,expires=0\r\n'
    c.cmd.side_effect = reply
    assert final_data(c, keys, rows, [], 0) == [v.decode() for v in actual]
    actual[0] = value(0, 2)
    fm.rejects(lambda: final_data(c, keys, rows, [], 0))
    actual[0] = None
    fm.rejects(lambda: final_data(c, keys, rows, [], 0))
    good = dict(completed=10, scheduled=10, within_window=10, lag_ns=[0] * 10, elapsed=1)
    fm.offered_valid([good], 1, 20)
    for poison in (dict(completed=9), dict(within_window=0), dict(lag_ns=[30_000_000]), dict(elapsed=4)):
        fm.rejects(lambda: fm.offered_valid([dict(good, **poison)], 1, 20))
    line, valid = fm.summary('flush_writer_wait', [{'valid': True}] * 6, 6)
    assert valid and 'status=VALID' in line and '\n' not in line
    assert not fm.summary('flush_writer_wait', [{'valid': True}] * 6, 6, error='bad')[1]
    print('flush_writer_wait selftest: PASS')
    return 0


def main():
    p = fm.common_parser(__doc__)
    fm.pacing_options(p)
    p.add_argument('--schedules', default='same-key,disjoint-key,no-flush')
    p.add_argument('--population', type=int, default=0)
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return fm.campaign(args, 'flush_writer_wait', cells(args), run, calibrate)


if __name__ == '__main__':
    sys.exit(main())
