#!/usr/bin/env python3
"""SET p32 and 1:1 GET/SET p32 under off, everysec, always and live BGSAVE."""
import json
import statistics
import sys
import time

import survey as s


def cells(args):
    s.require(args.always_seconds > 0 and args.bgsave_interval > 0, 'invalid persistence duration')
    return [dict(name=f'{cmd}-{mode}', workload=s.workload(cmd), keys=args.keys, connections=args.connections,
                 pipeline=32, persistence=mode, seconds=(2 if args.smoke else min(args.seconds, args.always_seconds))
                 if mode == 'always' else args.seconds)
            for cmd in ('SET', 'MIX') for mode in s.select(args.persistence, ('off', 'everysec', 'always', 'bgsave'))]


def bgsave_valid(events):
    s.require(len(events) >= 2, 'BGSAVE loop did not complete at least two saves during load')
    s.require(all(e['status'] == 'ok' and e['end'] > e['start'] and e['during_load'] for e in events), 'BGSAVE witness failed')


def run(args, cell, arm, folder):
    events = []
    with s.server(args, arm, folder, cell['persistence']) as (_, conn):
        s.seed(args, conn, folder, cell)
        baseline = s.fm.info(conn)
        def during(process):
            # Separate control connection, no interference with main INFO snapshots.
            control = s.Resp(args.port, args.timeout)
            try:
                while process.poll() is None:
                    start = time.monotonic()
                    before = s.fm.info(control)
                    reply = control.cmd('BGSAVE')
                    s.require(reply == b'Background saving started', f'BGSAVE rejected: {reply!r}')
                    while True:
                        info = s.fm.info(control)
                        if int(info['rdb_bgsave_in_progress']) == 0:
                            break
                        s.require(time.monotonic() - start < args.timeout, 'BGSAVE timed out')
                        time.sleep(.005)
                    event = dict(start=start, end=time.monotonic(), status=info['rdb_last_bgsave_status'],
                                 during_load=process.poll() is None, before=before, after=info)
                    events.append(event)
                    s.append(folder / 'bgsave-events.jsonl', event)
                    if process.poll() is not None:
                        break
                    time.sleep(.1 if args.smoke else args.bgsave_interval)
            finally:
                control.close()
        result = s.native(args, conn, folder / 'load', cell['workload']['cycle'], cell['keys'],
                          cell['connections'], 32, seconds=cell['seconds'],
                          during=during if cell['persistence'] == 'bgsave' else None)
        after = s.fm.info(conn)
        if cell['persistence'] == 'bgsave':
            # A save started near the end may finish after load; retain it but
            # require at least two entirely witnessed within the active interval.
            bgsave_valid([e for e in events if e['during_load']])
            s.require(sum(e['during_load'] for e in events) >= 2, 'no live BGSAVE loop')
        if cell['persistence'] in ('everysec', 'always'):
            s.require(int(after['aof_enabled']) == 1 and after['aof_last_write_status'] == 'ok', 'AOF inactive or failed')
            s.require(int(after['aof_current_size']) > int(baseline['aof_current_size']), 'AOF did not grow during load')
            s.require(sum(p.stat().st_size for p in (folder / 'data').rglob('*') if p.is_file()) > 0, 'AOF produced no file')
        result.update(persistence=cell['persistence'], workload=cell['workload']['name'],
                      persistence_before=baseline, persistence_after=after, bgsave_events=events)
        return result


def losses(records):
    groups = {}
    for row in records:
        groups.setdefault((row['arm'], row['workload'], row['block']), {}).setdefault(row['persistence'], []).append(row['ops_per_second'])
    result = []
    for (arm, workload, block), modes in groups.items():
        s.require('off' in modes, 'off baseline is required for persistence loss')
        off = statistics.mean(modes['off'])
        s.require(off > 0, 'zero off baseline')
        for mode, values in modes.items():
            rate = statistics.mean(values)
            result.append(dict(arm=arm, workload=workload, block=block, persistence=mode,
                               off_ops_per_second=off, ops_per_second=rate, throughput_loss_percent=100 * (1 - rate / off)))
    return result


def finish(args, records):
    s.save(args.output / 'persistence-loss.json', losses(records))


def selftest():
    s.base_selftest()
    good = dict(status='ok', start=1, end=2, during_load=True)
    bgsave_valid([good, good])
    for events in ([], [good], [good, dict(good, status='err')], [good, dict(good, during_load=False)]):
        s.rejects(lambda: bgsave_valid(events))
    base = dict(arm='redis-4', workload='SET', block=0)
    rows = [dict(base, persistence=mode, ops_per_second=rate) for mode, rate in (('off', 100), ('always', 60))]
    assert losses(rows)[1]['throughput_loss_percent'] == 40
    s.rejects(lambda: losses(rows[1:]))
    print('survey_persist selftest: PASS')
    return 0


def main():
    p = s.parser(__doc__)
    p.add_argument('--persistence', default='off,everysec,always,bgsave')
    p.add_argument('--always-seconds', type=float, default=5)
    p.add_argument('--bgsave-interval', type=float, default=.5)
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return s.campaign(args, 'survey_persist', cells, run, finish=finish)


if __name__ == '__main__':
    sys.exit(main())
