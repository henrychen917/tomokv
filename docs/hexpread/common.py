#!/usr/bin/env python3
"""Compare ordinary lazy expiry replies, notifications and INFO counter deltas with Redis 7.4."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import aoffix2 as h
from hexpread import subscribe, events, stats, deadline_passed


def run(server):
    c = server.client()
    assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
    assert c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'Egh') == b'OK'
    sub = subscribe(server)
    rows = []
    for limit in (512, 0):
        assert c.cmd('CONFIG', 'SET', 'hash-max-listpack-entries', limit) == b'OK'
        for resp in (2, 3):
            c.cmd('HELLO', resp)
            assert c.cmd('FLUSHDB') == b'OK'
            assert c.cmd('HSET', 'common', 'f', 'old', 'g', 'keep') == 2
            for field, expected_events in [('f', [['hexpired', 'common']]),
                                           ('g', [['hexpired', 'common'], ['del', 'common']])]:
                for attempt in range(3):
                    c.cmd('HSET', 'common', field, 'value')
                    deadline = time.time_ns() // 1_000_000 + 500
                    assert c.cmd('HPEXPIREAT', 'common', deadline, 'FIELDS', 1, field) == [1]
                    live = c.cmd('HGET', 'common', field)
                    if time.time_ns() // 1_000_000 < deadline:
                        assert live == b'value'
                        break
                    h.emit('missed_arm', attempt=attempt)
                else:
                    raise AssertionError('three fresh common TTL arms missed the deadline')
                events(sub)
                before = stats(c)
                deadline_passed(deadline)
                assert c.cmd('HGET', 'common', field) is None
                after = stats(c)
                observed = events(sub, required=len(expected_events))
                field_counter = 'expired_subkeys' if h.ARGS.oracle else 'expired_hash_fields'
                row = dict(limit=limit, resp=resp, field=field, reply=None, events=observed,
                           fields_expired=after[field_counter] - before[field_counter],
                           keys_expired=after['expired_keys'] - before['expired_keys'])
                h.emit('common', **row)
                rows.append(row)
                assert observed == expected_events, (observed, expected_events)
                assert row['fields_expired'] == 1 and row['keys_expired'] == 0, row
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), default='1s')
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--oracle', action='store_true')
    p.add_argument('--atomic', type=int, default=1)
    p.add_argument('--compare', type=Path)
    a = p.parse_args()
    a.binary, a.artifacts = a.binary.resolve(), a.artifacts.resolve()
    a.artifacts.mkdir(parents=True, exist_ok=False)
    a.engine, a.ratio = 'uring', '6:2'
    h.ARGS = a
    h.emit('arm', binary=str(a.binary), mode=a.mode, atomic=a.atomic, oracle=a.oracle,
           sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest())
    options = ['--enable-debug-command', 'yes'] if a.oracle else ['--atomic', str(a.atomic)]
    with h.Server(options) as server:
        rows = run(server)
    (a.artifacts / 'common.json').write_text(json.dumps(rows, indent=2) + '\n')
    if a.compare:
        assert rows == json.loads(a.compare.read_text()), 'target differs from Redis 7.4'
    h.emit('pass')


if __name__ == '__main__':
    main()
