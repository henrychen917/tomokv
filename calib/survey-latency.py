#!/usr/bin/env python3
"""Fixed offered loads, calibrated on Redis io-threads 4, retaining every observation."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import survey as s


def cells(args):
    fractions = [float(x) for x in args.fractions.split(',')]
    s.require(fractions and len(set(fractions)) == len(fractions) and all(0 < x < 1 for x in fractions), 'invalid offered fractions')
    s.require(args.calibration_seconds > 0 and args.max_lag_ms > 0, 'invalid calibration/deadline setting')
    return [dict(name=f'{cmd}-load{fraction:g}', workload=s.workload(cmd), fraction=fraction,
                 pipeline=1, keys=args.keys, connections=args.connections)
            for cmd in s.select(args.commands, ('GET', 'SET', 'HGET', 'LPUSH_RPOP', 'ZADD')) for fraction in fractions]


def calibration_capacity(rows):
    """Require a plateau between two concurrency rungs; never use generator saturation as capacity."""
    s.require(len(rows) >= 2 and all(r['ops_per_second'] > 0 for r in rows), 'missing calibration rung')
    s.require(not any(r['generator_busy'] for r in rows), 'calibration is generator limited; use more load workers')
    lower, upper = rows[-2:]
    relative = abs(upper['ops_per_second'] / lower['ops_per_second'] - 1)
    s.require(relative <= .05, 'Redis capacity has no plateau within 5%; increase --calibration-connections')
    return min(lower['ops_per_second'], upper['ops_per_second'])


def prepare(args, selected):
    by_command = {c['workload']['name']: c for c in selected}
    rungs = s.numbers(args.calibration_connections)
    if args.smoke:
        rungs = [4, 8]
    s.require(len(rungs) >= 2 and rungs == sorted(rungs), 'calibration needs increasing connection rungs')
    for cmd, cell in by_command.items():
        rows = []
        for rung in rungs:
            folder = args.output / 'calibration' / cmd / f'connections-{rung}'
            trial = dict(cell, connections=rung, pipeline=32, seconds=2 if args.smoke else args.calibration_seconds)
            result = s.run_throughput(args, trial, 'redis-4', folder)
            rows.append(dict(result, connections=rung))
            s.save(folder / 'calibration.json', rows[-1])
        if args.smoke:
            # A smoke verifies the entire pacing path at a deliberately low load.
            # It makes no capacity assertion on a shared box.
            capacity = min(r['ops_per_second'] for r in rows) * .01
            label = 'SMOKE_ONLY 1% calibration rate; not a capacity estimate'
        else:
            capacity = calibration_capacity(rows)
            label = 'Redis4 conservative minimum of final two closed-loop p32 plateau rungs'
        s.save(args.output / 'calibration' / cmd / 'capacity.json', dict(capacity=capacity, label=label, rungs=rungs))
        for target in selected:
            if target['workload']['name'] == cmd:
                target['offered'] = capacity * target['fraction']
                target['calibration'] = label
    s.save(args.output / 'cells.json', selected)


def run(args, cell, arm, folder):
    with s.server(args, arm, folder) as (_, conn):
        s.seed(args, conn, folder, cell)
        result = s.native(args, conn, folder / 'load', cell['workload']['cycle'], cell['keys'],
                          cell['connections'], 1, offered=cell['offered'], raw=True)
        result.update(offered_ops_per_second=cell['offered'], fraction=cell['fraction'],
                      capacity_basis=cell['calibration'], latency_basis='scheduled send to complete reply',
                      rtt_latency=result['latency'])
        result['latency'] = result['scheduled_latency']
        return result


def selftest():
    s.base_selftest()
    assert calibration_capacity([dict(ops_per_second=100, generator_busy=False), dict(ops_per_second=102, generator_busy=False)]) == 100
    for rows in ([], [dict(ops_per_second=100, generator_busy=False)] * 1,
                 [dict(ops_per_second=r, generator_busy=False) for r in (100, 200)],
                 [dict(ops_per_second=100, generator_busy=True)] * 2):
        s.rejects(lambda: calibration_capacity(rows))
    h = dict(n=10, max=1_000_000, bins=[[1_000_000, 10]])
    worker = dict(completed=10, primary=10, cycles=10, finish_ns=1_000_000_001,
                  scheduled=10, counts=[10], cpu_seconds=.1, within=10, rtt=h, response=h, lag=h)
    doc = dict(valid=True, epoch_ns=1, workers=[worker])
    operations = s.workload('GET')['cycle']
    assert s.validate_client(doc, operations, 1, offered=10)['completed'] == 10
    for poison in (dict(scheduled=9), dict(counts=[9]), dict(primary=9), dict(lag=dict(h, max=30_000_000))):
        s.rejects(lambda: s.validate_client(dict(doc, workers=[dict(worker, **poison)]), operations, 1, offered=10))
    print('survey_latency selftest: PASS')
    return 0


def main():
    p = s.parser(__doc__)
    p.add_argument('--commands', default='all')
    p.add_argument('--fractions', default='.25,.5,.75')
    p.add_argument('--calibration-seconds', type=float, default=5)
    p.add_argument('--calibration-connections', default='256,512,1024')
    p.add_argument('--max-lag-ms', type=float, default=20)
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return s.campaign(args, 'survey_latency', cells, run, prepare)


if __name__ == '__main__':
    sys.exit(main())
