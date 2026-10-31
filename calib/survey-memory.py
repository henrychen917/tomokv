#!/usr/bin/env python3
"""Resident and allocator bytes per live key, before/after deleting exactly half."""
import copy
import sys
import time
from unittest.mock import Mock, patch

import survey as s


SHAPES = ('string16', 'string128', 'string1024', 'hash10', 'list10', 'set10', 'zset10', 'ttl16')


def image(shape):
    command = {'hash10': 'HGET', 'list10': 'LINDEX', 'set10': 'SISMEMBER', 'zset10': 'ZRANK'}.get(shape, 'GET')
    size = int(shape[6:]) if shape.startswith('string') else 16
    w = s.workload(command, size=size, cardinality=10)
    if shape == 'ttl16':
        w['init'][0]['command'] += ['EX', 86400]
    return w


def cells(args):
    s.require(args.settle >= 0, 'negative settle')
    populations = [32, 128] if args.smoke else s.numbers(args.populations)
    s.require(all(n % 2 == 0 for n in populations), 'populations must be even')
    return [dict(name=f'{shape}-n{n}', shape=shape, workload=image(shape), keys=n, connections=4, pipeline=1)
            for shape in s.select(args.shapes, SHAPES) for n in populations]


def sample(conn, pid, expected):
    info = s.fm.info(conn)
    keys = conn.cmd('DBSIZE')
    s.require(keys == expected, f'memory population mismatch: {keys} != {expected}')
    used, rss = int(info['used_memory']), s.fm.rss(pid)
    s.require(used >= 0 and (expected == 0 or used > 0) and rss > 0, 'invalid memory counters')
    return dict(keys=keys, used_memory=used, rss_bytes=rss,
                info_used_memory_rss=int(info['used_memory_rss']), info=info)


def per_key(row, empty):
    n = row['keys']
    s.require(n > 0, 'zero live-key denominator')
    return dict(row, used_memory_per_key=row['used_memory'] / n, rss_per_key=row['rss_bytes'] / n,
                used_memory_incremental_per_key=(row['used_memory'] - empty['used_memory']) / n,
                rss_incremental_per_key=(row['rss_bytes'] - empty['rss_bytes']) / n,
                rss_over_used=row['rss_bytes'] / row['used_memory'])


def run(args, cell, arm, folder):
    with s.server(args, arm, folder) as (process, conn):
        empty = sample(conn, process.pid, 0)
        s.seed(args, conn, folder, cell)
        time.sleep(2 if args.smoke else args.settle)
        loaded = per_key(sample(conn, process.pid, cell['keys']), empty)
        # Delete the first half of the deterministic key range, with an exact
        # integer-1 reply for every DEL. This is not "half of attempted sends".
        delete = [s.op(('DEL', s.KEY), 1)]
        deleted = s.native(args, conn, folder / 'delete', delete, cell['keys'], min(32, cell['keys'] // 2),
                           pipeline=32, count=cell['keys'] // 2, seconds=3600)
        time.sleep(.05 if args.smoke else args.settle)
        half = per_key(sample(conn, process.pid, cell['keys'] // 2), empty)
        # Independent endpoints catch a DEL range or placeholder error.
        s.require(conn.cmd('EXISTS', 'sv:100000000000') == 0, 'first half survived DEL')
        s.require(conn.cmd('EXISTS', f'sv:{100000000000 + cell["keys"] - 1:012d}') == 1, 'surviving half was deleted')
        for row in (loaded, half):
            s.require(int(row['info']['expired_keys']) == 0 and int(row['info']['evicted_keys']) == 0, 'memory image expired/evicted')
        return dict(empty=empty, loaded=loaded, after_half_del=half, deletion=deleted,
                    fragmentation=dict(rss_reclaimed=loaded['rss_bytes'] - half['rss_bytes'],
                    used_reclaimed=loaded['used_memory'] - half['used_memory']), shape=cell['shape'])


def selftest():
    s.base_selftest()
    empty = dict(used_memory=100, rss_bytes=200)
    row = dict(keys=5, used_memory=150, rss_bytes=300)
    result = per_key(row, empty)
    assert result['used_memory_per_key'] == 30 and result['used_memory_incremental_per_key'] == 10
    assert result['rss_per_key'] == 60
    s.rejects(lambda: per_key(dict(row, keys=0), empty))
    conn = Mock()
    conn.cmd.side_effect = [b'used_memory:100\r\nused_memory_rss:200\r\n', 4]
    s.rejects(lambda: sample(conn, 0, 5))
    conn.cmd.side_effect = [b'used_memory:0\r\nused_memory_rss:200\r\n', 0]
    with patch.object(s.fm, 'rss', return_value=200):
        assert sample(conn, 0, 0)['used_memory'] == 0  # TomoKV's empty payload accounting
        conn.cmd.side_effect = [b'used_memory:0\r\nused_memory_rss:200\r\n', 5]
        s.rejects(lambda: sample(conn, 0, 5))
    assert image('ttl16')['init'][0]['command'][-2:] == ['EX', 86400]
    assert len(image('hash10')['init'][0]['command']) == 22
    print('survey_memory selftest: PASS')
    return 0


def main():
    p = s.parser(__doc__)
    p.add_argument('--populations', default='1000000,10000000')
    p.add_argument('--shapes', default='all')
    p.add_argument('--settle', type=float, default=5)
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return s.campaign(args, 'survey_memory', cells, run)


if __name__ == '__main__':
    sys.exit(main())
