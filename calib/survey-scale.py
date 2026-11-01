#!/usr/bin/env python3
"""Connection scaling p1 and value-size scaling p8, same client settings on both arms."""
import sys
from types import SimpleNamespace

import survey as s


def cells(args):
    selected = s.select(args.dimensions, ('connections', 'values'))
    rows = []
    if 'connections' in selected:
        values = [4, 8, 16, 32] if args.smoke else s.numbers(args.connection_counts)
        for count in values:
            for cmd in ('GET', 'SET'):
                rows.append(dict(name=f'connections-{count}-{cmd}-p1', workload=s.workload(cmd),
                                 connections=count, keys=args.keys, pipeline=1, dimension='connections'))
    if 'values' in selected:
        for size in s.numbers(args.value_sizes):
            for cmd in ('GET', 'SET'):
                rows.append(dict(name=f'bytes-{size}-{cmd}-p8', workload=s.workload(cmd, size=size),
                                 connections=args.connections, keys=args.keys, pipeline=8, dimension='values'))
    return rows


def selftest():
    s.base_selftest()
    args = SimpleNamespace(dimensions='connections,values', connection_counts='50,500,5000,10000',
                           value_sizes='16,1024,16384,262144', smoke=False, connections=512, keys=1024)
    rows = cells(args)
    assert len(rows) == 16 and len({r['name'] for r in rows}) == 16
    assert {r['connections'] for r in rows if r['dimension'] == 'connections'} == {50, 500, 5000, 10000}
    assert all(r['pipeline'] == (1 if r['dimension'] == 'connections' else 8) for r in rows)
    s.rejects(lambda: s.numbers('50,50'))
    s.rejects(lambda: s.numbers('0'))
    print('survey_scale selftest: PASS')
    return 0


def main():
    p = s.parser(__doc__)
    p.add_argument('--dimensions', default='connections,values')
    p.add_argument('--connection-counts', default='50,500,5000,10000')
    p.add_argument('--value-sizes', default='16,1024,16384,262144')
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return s.campaign(args, 'survey_scale', cells)


if __name__ == '__main__':
    sys.exit(main())
