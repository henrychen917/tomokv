#!/usr/bin/env python3
"""EX4.17: exact bucket balance and recovery of authenticated PRE files."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

from compat2_support import Client, arguments, save, server, wait_for


def persistence_info(c):
    return {k: v for line in c.cmd('INFO', 'persistence').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)]}

BUCKETS = 16384
SHARDS = 200
MASK = (1 << 64) - 1
FIXTURE = Path(__file__).parent / 'fixtures' / 'dispatchfix-pre'


def mix(h):
    h = ((h ^ (h >> 33)) * 0xff51afd7ed558ccd) & MASK
    h = ((h ^ (h >> 33)) * 0xc4ceb9fe1a85ec53) & MASK
    return h ^ (h >> 33)


def bucket_keys(seed):
    keys = {}
    initial = (0x9e3779b97f4a7c15 ^ ((8 * 0xff51afd7ed558ccd) & MASK)) ^ seed
    for value in range(1000000):
        bucket = mix(mix(initial ^ value)) & (BUCKETS - 1)
        keys.setdefault(bucket, struct.pack('<Q', value))
        if len(keys) == BUCKETS:
            return [keys[b] for b in range(BUCKETS)]
    raise AssertionError(f'bounded key search covered only {len(keys)} buckets')


def packed(value):
    if isinstance(value, bytes):
        return {'hex': value.hex()}
    if isinstance(value, (list, tuple)):
        return [packed(x) for x in value]
    return value


def unpacked(value):
    if isinstance(value, dict):
        return bytes.fromhex(value['hex'])
    if isinstance(value, list):
        return [unpacked(x) for x in value]
    return value


def options(data, aof=False, active=False):
    return ['--dir', str(data.resolve()), '--hash', 'mix64', '--shards', str(SHARDS),
            '--appendonly', 'yes' if aof else 'no', '--appendfsync', 'always',
            '--auto-aof-rewrite-percentage', '0', '--key-lb', '1' if active else '0',
            '--client-lb', '1' if active else '0', '--read-local', '1' if active else '0']


def distribution(c, data, output):
    assert c.cmd('SAVE') == b'OK'
    header = (data / 'dump.tomo').read_bytes()
    seed = struct.unpack_from('<Q', header, 40)[0]
    keys = bucket_keys(seed)
    routes = []
    for first in range(0, BUCKETS, 256):
        routes.extend(c.cmd('DEBUG', 'SHARDS', *keys[first:first + 256]))
    counts = Counter(route[0] for route in routes)
    expected = [b * SHARDS // BUCKETS for b in range(BUCKETS)]
    failures = sum(route[0] != expected[b] for b, route in enumerate(routes))
    save(output / 'buckets.json', dict(seed=seed, counts=sorted(counts.items()),
         mismatched_buckets=failures, covered=len(routes), owners=sorted({r[1] for r in routes})))
    assert sum(counts.values()) == BUCKETS and len(counts) == SHARDS
    return keys, (max(counts.values()) - min(counts.values()) <= 1 and failures == 0)


def dataset(c, oracle, keys):
    rows = []
    def same(*argv):
        actual, expected = c.cmd(*argv), oracle.cmd(*argv)
        assert actual == expected, (argv, actual, expected)
        rows.append(dict(argv=packed(argv), reply=packed(expected)))
    selected = sorted(set(range(0, BUCKETS, 32)) |
                      {((s * BUCKETS + SHARDS - 1) // SHARDS) for s in range(SHARDS)} |
                      set(range(16110, BUCKETS, 3)))
    chosen = [keys[b] for b in selected]
    same('SET', 'stale', 'before-flush')
    same('FLUSHALL')
    for first in range(0, len(chosen), 64):
        pairs = [part for key in chosen[first:first+64] for part in (key, b'v:' + key)]
        same('MSET', *pairs)
    same('SELECT', 1)
    for key in chosen[::19]:
        same('SET', key, b'before-db-flush')
    same('FLUSHDB')
    for key in chosen[::11]:
        same('SET', key, b'db-one:' + key)
    same('SELECT', 0)
    same('DEL', *chosen[::7])
    same('HSET', 'typed:hash', 'f', 'v')
    same('RPUSH', 'typed:list', 'a', 'b', 'c')
    same('SADD', 'typed:set', 'a')
    same('ZADD', 'typed:zset', 3, 'm')
    same('XADD', 'typed:stream', '1-0', 'f', 'v')
    same('SET', 'expired', 'gone')
    same('PEXPIREAT', 'expired', 1)
    same('SET', 'ttl', 'live')
    same('PEXPIREAT', 'ttl', 4102444800000)
    same('SWAPDB', 0, 2)
    same('SET', 'after-swap', 'zero')
    checks = []
    for db in (0, 1, 2):
        same('SELECT', db)
        checks.append(dict(argv=['SELECT', db], reply=packed(b'OK')))
        for key in chosen + [b'stale', b'expired', b'ttl', b'after-swap']:
            argv = ['GET', key]
            actual, expected = c.cmd(*argv), oracle.cmd(*argv)
            assert actual == expected, (db, key, actual, expected)
            checks.append(dict(argv=packed(argv), reply=packed(expected)))
        for argv in [('HGETALL', 'typed:hash'), ('LRANGE', 'typed:list', 0, -1),
                     ('SMEMBERS', 'typed:set'), ('ZRANGE', 'typed:zset', 0, -1, 'WITHSCORES'),
                     ('XRANGE', 'typed:stream', '-', '+'), ('PEXPIRETIME', 'ttl'), ('DBSIZE',)]:
            actual, expected = c.cmd(*argv), oracle.cmd(*argv)
            assert actual == expected, (db, argv, actual, expected)
            checks.append(dict(argv=packed(argv), reply=packed(expected)))
    return rows, checks


def check(c, checks):
    for row in checks:
        argv, expected = unpacked(row['argv']), unpacked(row['reply'])
        actual = c.cmd(*argv)
        assert actual == expected, (argv, actual, expected)


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    record = os.environ.get('DISPATCHFIX_RECORD_PRE') == '1'
    data = a.output / 'written'
    data.mkdir()
    # Use the third reserved gate port so both listeners can avoid even
    # ephemeral source ports used by concurrent lanes. The gate reserves three.
    with server(a.binary, a.output / 'balance', a.port, a.cores, a.mode, a.engine,
                extra=options(data, aof=record)), \
         server(a.oracle, a.output / 'oracle', a.port + 2, a.cores, oracle=True):
        with Client(a.port) as c, Client(a.port + 2) as oracle:
            keys, balanced = distribution(c, data, a.output)
            if record:
                sha = hashlib.sha256(a.binary.read_bytes()).hexdigest()
                expected_sha = (Path(__file__).parents[1] / 'docs/dispatchfix/pre-sha256.txt').read_text().split()[0]
                assert sha == expected_sha, 'fixture recording requires the authenticated PRE binary'
                rows, checks = dataset(c, oracle, keys)
                (a.output / 'commands.json').write_text(json.dumps(rows, indent=2) + '\n')
                (a.output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
                assert c.cmd('SAVE') == b'OK'
    if record:
        fixture = a.output / 'fixture'
        fixture.mkdir()
        for source in [data / 'dump.tomo', *sorted((data / 'appendonlydir').glob('*'))]:
            destination = fixture / (str(source.relative_to(data)) + '.gz')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(gzip.compress(source.read_bytes(), mtime=0))
        shutil.copy(a.output / 'checks.json', fixture / 'checks.json')
        shutil.copy(a.output / 'commands.json', fixture / 'commands.json')
        save(fixture / 'origin.json', dict(commit='a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e',
             sha256=sha, mode=a.mode, engine=a.engine, shards=SHARDS))
    else:
        fixture = FIXTURE
        checks = json.loads((fixture / 'checks.json').read_text())
    # Both recovery paths run on PRE as well, even when the balance assertion fails.
    for kind in ('snapshot', 'aof'):
        restored = a.output / f'{kind}-data'
        restored.mkdir()
        sources = list((fixture / 'appendonlydir').glob('*.gz')) if kind == 'aof' else [fixture / 'dump.tomo.gz']
        for source in sources:
            destination = restored / source.relative_to(fixture).with_suffix('')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(gzip.decompress(source.read_bytes()))
        for phase in ('load', 'restart', 'rewrite-restart'):
            with server(a.binary, a.output / f'{kind}-{phase}', a.port, a.cores, a.mode,
                        a.engine, extra=options(restored, aof=kind == 'aof', active=True)):
                with Client(a.port) as c:
                    check(c, checks)
                    assert c.cmd('SELECT', 0) == b'OK'
                    if phase != 'load':
                        assert c.cmd('SELECT', 3) == b'OK'
                        assert c.cmd('GET', 'post-upgrade') == b'new-value'
                        assert c.cmd('SELECT', 0) == b'OK'
                    assert c.cmd('SET', 'post-upgrade', 'new-value') == b'OK'
                    # DBSIZE is among the oracle checks; remove the extra key before
                    # the next pass, then add it on a separate logical database.
                    assert c.cmd('DEL', 'post-upgrade') == 1
                    assert c.cmd('SELECT', 3) == b'OK'
                    assert c.cmd('SET', 'post-upgrade', 'new-value') == b'OK'
                    if kind == 'snapshot':
                        assert c.cmd('SAVE') == b'OK'
                    elif phase == 'restart':
                        rewrites = int(persistence_info(c)['aof_rewrites'])
                        assert c.cmd('BGREWRITEAOF') == b'Background append only file rewriting started'
                        wait_for(lambda: int(persistence_info(c)['aof_rewrites']) > rewrites and
                                 persistence_info(c)['aof_rewrite_in_progress'] == '0',
                                 'AOF rewrite did not finish', 15)
                        assert b'aof_last_bgrewrite_status:ok\r\n' in c.cmd('INFO', 'persistence')
    assert balanced, 'EX4.17: uniform routing leaves unequal bucket counts (see buckets.json)'
    print(f'EX4.17 PASS: all {BUCKETS} buckets; PRE snapshot/AOF, restart and rewrite recovery')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
