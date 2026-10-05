#!/usr/bin/env python3
"""EX1/EX3 live witness. Connects only to a gate/maintainer-owned fresh listener."""
import sys
import time
from _lib import Conn, encode, shards_of, topology


def keyspace(raw):
    for line in raw.decode().splitlines():
        if line.startswith('db0:'):
            values = dict(part.split('=') for part in line[4:].split(','))
            return int(values['keys']), int(values['expires'])
    return 0, 0


def published(conn, size, expires):
    deadline = time.monotonic() + 2
    while True:
        actual = conn.must('DBSIZE'), keyspace(conn.must('INFO', 'keyspace'))
        if actual == (size, (size, expires)): return
        assert time.monotonic() < deadline, ('publication never reached expected values', actual,
                                             size, expires)
        time.sleep(.005)


def run(host, port):
    a, b = Conn(host, port), Conn(host, port)
    try:
        shape = topology(a)
        assert len(shape.shard_owner) == 16, 'gate geometry must have 16 shards'
        assert a.must('DBSIZE') == 0, 'witness requires a fresh boot'
        selected = {}
        for base in range(0, 4096, 128):
            keys = [f'exbatch:publish:{i}' for i in range(base, base + 128)]
            for key, (sid, _) in zip(keys, shards_of(a, keys)):
                selected.setdefault(sid, key)
            if len(selected) == 16: break
        assert len(selected) == 16, 'all shard arms must open; no skip'
        # A key on every shard and a pipeline suffix on another shard. The
        # DEBUG proof, not the spelling, establishes the non-last shard coverage.
        keys = [selected[sid] for sid in sorted(selected)]
        a.raw(b''.join(encode('SET', key, 'v') for key in keys))
        assert [a.read() for _ in keys] == [b'OK'] * 16
        published(b, 16, 0)
        a.raw(b''.join(encode('PEXPIRE', key, 600000) for key in keys[:-1]))
        assert [a.read() for _ in keys[:-1]] == [1] * 15
        published(b, 16, 15)
        a.raw(b''.join(encode('DEL', key) for key in keys[:-1]))
        assert [a.read() for _ in keys[:-1]] == [1] * 15
        published(b, 1, 0)
        key = keys[-1]
        assert a.must('WATCH', key) == b'OK'
        assert b.must('SET', key, 'foreign') == b'OK'
        assert a.must('MULTI') == b'OK'
        assert a.must('SET', key, 'must-abort') == b'QUEUED'
        assert a.must('EXEC') is None
        assert b.must('GET', key) == b'foreign'
        for cleanup in ('UNWATCH', 'DISCARD'):
            assert a.must('WATCH', key) == b'OK'
            if cleanup == 'DISCARD': assert a.must('MULTI') == b'OK'
            assert a.must(cleanup) == b'OK'
            assert b.must('SET', key, 'after-cleanup') == b'OK'
            assert a.must('MULTI') == b'OK'
            assert a.must('SET', key, 'committed') == b'QUEUED'
            assert a.must('EXEC') == [b'OK']
        assert a.must('WATCH', key) == b'OK'
        assert a.must('SWAPDB', 0, 1) == b'OK'
        assert a.must('MULTI') == b'OK'
        assert a.must('SET', key, 'must-abort') == b'QUEUED'
        assert a.must('EXEC') is None
        assert a.must('SWAPDB', 0, 1) == b'OK'
        assert a.must('GET', key) == b'committed'
        print(f'PASS exbatch {shape.mode}: non-last shard gauges, WATCH/UNWATCH/EXEC/DISCARD/SWAPDB')
    finally:
        a.close(); b.close()


if __name__ == '__main__':
    run(sys.argv[1], int(sys.argv[2]))
