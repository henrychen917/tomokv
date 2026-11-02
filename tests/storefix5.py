#!/usr/bin/env python3
"""Directed storefix5 correctness witnesses; accepts an already running gate server."""
import argparse
import json
import time
import threading
from collections import Counter
from _lib import Conn, RespError, encode, info


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
    # WRITE pause holds logical expiry even for a read-only RANDOMKEY. A new
    # connection is unnecessary: CLIENT UNPAUSE itself is allowed through.
    assert c.cmd('SET', 'pause-image', 'v', 'PX', 1000) == b'OK'
    assert c.cmd('CLIENT', 'PAUSE', 10000, 'WRITE') == b'OK'
    time.sleep(1.1)
    assert c.cmd('RANDOMKEY') == b'pause-image'
    assert c.cmd('CLIENT', 'UNPAUSE') == b'OK'
    assert c.cmd('RANDOMKEY') is None
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
    previous_slowlog = c.cmd('CONFIG', 'GET', 'slowlog-log-slower-than')[1]
    assert c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', 0) == b'OK'
    for length in (16, 1024, 65536, 1 << 20, 4 << 20):
        original = b'x' * length
        assert c.cmd('SET', 'append', original, 'PX', 60000) == b'OK'
        times = []
        command_times = []
        for i in range(5):
            start = time.perf_counter_ns()
            assert c.cmd('APPEND', 'append', 'z') == length + i + 1
            times.append((time.perf_counter_ns() - start) / 1000)
            entries = c.cmd('SLOWLOG', 'GET', 1)
            assert entries and entries[0][3][0].upper() == b'APPEND', entries
            command_times.append(entries[0][2])
        assert c.cmd('GET', 'append') == original + b'z' * 5
        assert 0 < c.cmd('PTTL', 'append') <= 60000
        assert c.cmd('OBJECT', 'ENCODING', 'append') == b'raw'
        assert c.cmd('APPEND', 'append', '') == length + 5
        result[length] = dict(single_call_us=times, slowlog_command_us=command_times,
                              value_and_ttl=True)
        assert c.cmd('DEL', 'append') == 1
    for original in (b'', b'123', b'a\0b'):
        assert c.cmd('SET', 'append', original) == b'OK'
        assert c.cmd('APPEND', 'append', b'\0z') == len(original) + 2
        assert c.cmd('GET', 'append') == original + b'\0z'
    assert c.cmd('DEL', 'append') == 1
    assert c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', previous_slowlog) == b'OK'
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


def memory_limit(c, limit, value_size, policy):
    """Finite population to pressure, including rejected writes; never a rate."""
    value = b'x' * value_size
    before = {k: int(v) for k, v in info(c, 'memory').items()
              if k in ('used_memory', 'used_memory_rss')}
    offered = max(10000, 2 * limit // (value_size + 32))
    accepted = refused = consecutive_refused = 0
    for start in range(0, offered, 256):
        commands = [('SET', f'memory:{i:012d}', value)
                    for i in range(start, min(start + 256, offered))]
        c.raw(b''.join(encode(*args) for args in commands))
        for _ in commands:
            reply = c.read()
            if reply == b'OK':
                accepted += 1
                consecutive_refused = 0
            else:
                assert isinstance(reply, RespError) and str(reply).startswith('OOM'), reply
                refused += 1
                consecutive_refused += 1
        if policy == 'noeviction' and consecutive_refused >= 1024: break
    time.sleep(.25)
    memory = {k: int(v) for k, v in info(c, 'memory').items()
              if k in ('used_memory', 'used_memory_rss')}
    keys = c.cmd('DBSIZE')
    evicted = int(info(c, 'stats')['evicted_keys'])
    result = dict(limit=limit, value_size=value_size, policy=policy, keys=keys,
                  accepted=accepted, refused=refused, evicted=evicted, before=before,
                  after=memory, rss_over_limit=memory['used_memory_rss']/limit)
    print(json.dumps(result), flush=True)
    assert keys > 0 and memory['used_memory'] >= limit * .8, result
    assert memory['used_memory'] <= limit + 16 * 18432, result
    assert refused if policy == 'noeviction' else evicted, result
    assert c.cmd('FLUSHALL') == b'OK'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('host'); p.add_argument('port', type=int)
    p.add_argument('case', choices=('randomkey', 'randomkey_footprint', 'append', 'idle', 'all'))
    a = p.parse_args()
    c = Conn(a.host, a.port, timeout=120)
    try:
        for case in (('randomkey', 'append') if a.case == 'all' else (a.case,)):
            globals()[case](c)
    finally:
        c.close()
