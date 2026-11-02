#!/usr/bin/env python3
"""Directed storefix5 correctness witnesses; accepts an already running gate server."""
import argparse
import json
import time
import threading
from collections import Counter
from _lib import Conn, encode, info


def populate(c, count, value=b'v'):
    for start in range(0, count, 128):
        args = ['MSET']
        for i in range(start, min(count, start + 128)):
            args.extend((f'storefix5:{i:012d}', value))
        assert c.cmd(*args) == b'OK'


def randomkey(c, strict=True):
    assert c.cmd('FLUSHALL') == b'OK'
    assert c.cmd('RANDOMKEY') is None
    assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
    for i in range(400):
        assert c.cmd('SET', f'expired:{i}', 'v', 'PX', 20) == b'OK'
    live = [b'live']
    if strict:
        # Prove every shard has a survivor: the witness cannot accidentally need
        # all shards just because the sole survivor was in the last retry shard.
        found = {}
        for i in range(10000):
            key = f'live:{i}'.encode()
            sid = c.cmd('DEBUG', 'SHARD', key)
            assert isinstance(sid, int), sid
            found.setdefault(sid, key)
            if len(found) == 16: break
        assert len(found) == 16, found
        live = list(found.values())
    for key in live:
        assert c.cmd('SET', key, 'v') == b'OK'
    time.sleep(.1)
    before = int(info(c, 'stats')['expired_keys'])
    assert c.cmd('RANDOMKEY') in live
    reaped = int(info(c, 'stats')['expired_keys']) - before
    assert c.cmd('DEL', *live) == len(live)
    assert c.cmd('RANDOMKEY') is None
    assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 1) == b'OK'
    assert c.cmd('FLUSHALL') == b'OK'
    keys = [f'uniform:{i}'.encode() for i in range(32)]
    for key in keys:
        assert c.cmd('SET', key, 'v') == b'OK'
    samples = 16384
    counts = Counter()
    for _ in range(samples // 64):
        c.raw(encode('RANDOMKEY') * 64)
        counts.update(c.read() for _ in range(64))
    assert set(counts) == set(keys), counts
    expected = samples / len(keys)
    chi2 = sum((counts[k] - expected)**2 / expected for k in keys)
    result = dict(expired_reaped_by_one_call=reaped, chi2=chi2, df=31,
                  samples=samples, counts={k.decode(): counts[k] for k in keys})
    print(json.dumps(result), flush=True)
    # PRE scans and reaps all 400 keys, independently of timing or RSS noise.
    if strict:
        assert reaped < 400, 'RANDOMKEY still visits every elapsed key on every shard'
        assert chi2 < 100, result
    assert c.cmd('FLUSHALL') == b'OK'
    assert c.cmd('MULTI') == b'OK'
    assert c.cmd('SET', 'transaction', 'v') == b'QUEUED'
    assert c.cmd('RANDOMKEY') == b'QUEUED'
    assert c.cmd('EXEC') == [b'OK', b'transaction']
    assert c.cmd('MULTI') == b'OK'
    assert c.cmd('DEL', 'transaction') == b'QUEUED'
    assert c.cmd('RANDOMKEY') == b'QUEUED'
    assert c.cmd('EXEC') == [1, None]
    databases = int(c.cmd('CONFIG', 'GET', 'databases')[1])
    if databases > 1:
        assert c.cmd('SELECT', 1) == b'OK'
        assert c.cmd('RANDOMKEY') is None
        assert c.cmd('SET', 'namespace-one', 'v') == b'OK'
        assert c.cmd('SELECT', 0) == b'OK'
        assert c.cmd('RANDOMKEY') is None
        assert c.cmd('SWAPDB', 0, 1) == b'OK'
        assert c.cmd('RANDOMKEY') == b'namespace-one'
        assert c.cmd('FLUSHALL') == b'OK'
    return result


def append(c):
    result = {}
    for length in (16, 1024, 65536, 1 << 20, 4 << 20):
        original = b'x' * length
        assert c.cmd('SET', 'append', original, 'PX', 60000) == b'OK'
        times = []
        for i in range(5):
            start = time.perf_counter_ns()
            assert c.cmd('APPEND', 'append', 'z') == length + i + 1
            times.append((time.perf_counter_ns() - start) / 1000)
        assert c.cmd('GET', 'append') == original + b'z' * 5
        assert 0 < c.cmd('PTTL', 'append') <= 60000
        assert c.cmd('OBJECT', 'ENCODING', 'append') == b'raw'
        assert c.cmd('APPEND', 'append', '') == length + 5
        result[length] = dict(single_call_us=times, value_and_ttl=True)
        assert c.cmd('DEL', 'append') == 1
    for original in (b'', b'123', b'a\0b'):
        assert c.cmd('SET', 'append', original) == b'OK'
        assert c.cmd('APPEND', 'append', b'\0z') == len(original) + 2
        assert c.cmd('GET', 'append') == original + b'\0z'
    assert c.cmd('DEL', 'append') == 1
    print(json.dumps(result), flush=True)
    return result


def randomkey_footprint(c):
    assert c.cmd('FLUSHALL') == b'OK'
    populate(c, 1000000)
    assert c.cmd('DBSIZE') == 1000000
    def memory():
        return {k: int(v) for k, v in info(c, 'memory').items()
                if k in ('used_memory', 'used_memory_rss', 'used_memory_peak')}
    before = memory()
    calls = []
    for _ in range(5):
        start = time.perf_counter_ns()
        key = c.cmd('RANDOMKEY')
        calls.append((time.perf_counter_ns() - start) / 1e6)
        assert key.startswith(b'storefix5:')
    single = memory()
    errors = []
    def worker():
        conn = Conn(c.host, c.port, timeout=120)
        try:
            conn.raw(encode('RANDOMKEY') * 16)
            assert all(conn.read().startswith(b'storefix5:') for _ in range(16))
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            conn.close()
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors, errors
    after = memory()
    result = dict(keys=1000000, single_call_ms=calls, before=before, single=single,
                  after_four_clients_16_calls=after)
    print(json.dumps(result), flush=True)
    assert c.cmd('FLUSHALL') == b'OK'
    assert after['used_memory_rss'] - before['used_memory_rss'] < 8 * 1024 * 1024, result
    return result


def idle(c, strict=True):
    assert c.cmd('CONFIG', 'SET', 'maxmemory', 0) == b'OK'
    assert c.cmd('FLUSHALL') == b'OK'
    populate(c, 10000, b'x' * 100)
    before = int(info(c, 'memory')['used_memory'])
    assert c.cmd('CONFIG', 'SET', 'maxmemory', '1gb') == b'OK'
    after = int(info(c, 'memory')['used_memory'])
    # Accounting queries must not create nodes or touch access times.
    observed = [int(info(c, 'memory')['used_memory']) for _ in range(5)]
    result = dict(before=before, armed=after, queries=observed)
    print(json.dumps(result), flush=True)
    assert c.cmd('CONFIG', 'SET', 'maxmemory', 0) == b'OK'
    assert c.cmd('FLUSHALL') == b'OK'
    if strict:
        assert after > before + 10000 * 16, 'idle clock missing from used_memory'
        assert all(v == after for v in observed), 'accounting has side effects'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('host'); p.add_argument('port', type=int)
    p.add_argument('case', choices=('randomkey', 'randomkey_footprint', 'append', 'idle'))
    a = p.parse_args()
    c = Conn(a.host, a.port, timeout=120)
    try:
        globals()[a.case](c)
    finally:
        c.close()
