#!/usr/bin/env python3
"""Shared survey mechanics. No production imports; stdlib + survey-client.cc.

All native completions are validated and exactly reconciled against INFO
commandstats. Histograms are pooled by counts, never by averaging percentiles.
"""
import argparse
import base64
from collections import Counter
import contextlib
import copy
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
from unittest.mock import Mock, patch

import flushmerit as fm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from abba_workloads import decode_histogram
Invalid, require, encode, cpus = fm.Invalid, fm.require, fm.encode, fm.cpus
KEY = 'sv:000000000000'
OTHER = 'sw:000000000000'
STREAM = 'ss:000000000000'
VALUE = b'x' * 16
COUNTERS = ('total_commands_processed', 'total_error_replies', 'keyspace_hits', 'keyspace_misses',
            'expired_keys', 'evicted_keys', 'rejected_connections', 'send_errors', 'peer_aborts',
            'atomic_txn_order_violations')
ZERO = ('total_error_replies', 'expired_keys', 'evicted_keys', 'rejected_connections',
        'send_errors', 'peer_aborts', 'atomic_txn_order_violations')


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + '\n')
    temporary.replace(path)


def append(path, value):
    with path.open('a') as f:
        f.write(json.dumps(value, allow_nan=False, default=str) + '\n')


def reply_wire(value):
    if isinstance(value, Status):
        return b'+' + value.value + b'\r\n'
    if isinstance(value, int):
        return b':%d\r\n' % value
    if value is None:
        return b'$-1\r\n'
    if isinstance(value, (list, tuple)):
        return b'*%d\r\n' % len(value) + b''.join(reply_wire(v) for v in value)
    value = value if isinstance(value, bytes) else str(value).encode()
    return b'$%d\r\n' % len(value) + value + b'\r\n'


class Status:
    def __init__(self, value=b'OK'):
        self.value = value

    def __str__(self):
        return 'RESP simple string: ' + self.value.decode('ascii')


class Resp(fm.Resp):
    """Preserve the exact wire for the behaviour sidecar, including RESP errors."""
    def read_wire(self):
        line = self.file.readline()
        require(line.endswith(b'\r\n') and len(line) >= 3, 'truncated RESP line')
        kind, data = line[:1], line[1:-2]
        if kind in (b'+', b'-', b':'):
            if kind == b':':
                int(data)
            return line
        require(kind in (b'$', b'*'), 'unknown RESP2 tag')
        n = int(data)
        require(n >= -1, 'invalid RESP length')
        if n == -1:
            return line
        if kind == b'*':
            return line + b''.join(self.read_wire() for _ in range(n))
        tail = self.file.read(n + 2)
        require(len(tail) == n + 2 and tail[-2:] == b'\r\n', 'truncated RESP bulk')
        return line + tail

    def wire(self, args):
        self.sock.sendall(encode(*args))
        return self.read_wire()


def op(command, expected, rule='exact', primary=True):
    return dict(command=list(command), expected=expected, rule=rule, primary=primary)


def write_script(path, operations):
    with path.open('wb') as f:
        f.write(f'{len(operations)}\n'.encode())
        for row in operations:
            request, expected = encode(*row['command']), reply_wire(row['expected'])
            f.write(f'{int(row["primary"])} {row["rule"]} {len(request)} {len(expected)}\n'.encode())
            f.write(request + expected)


def field(i):
    return f'f{i:05d}'


def member(i):
    return f'm{i:05d}'


def workload(name, size=16, cardinality=100):
    """Deterministic initial image, timed cycle, and explicit operation units.

    Refill/reset commands are in the script, excluded from primary ops, and
    counted separately. They consume real wall time. No hidden background work.
    """
    v = b'x' * size
    init = [op(('SET', KEY, v), Status(), primary=False)]
    cycle = []
    shape, n, key_multiplier = 'string', cardinality, 1
    note = ''
    if name in ('GET', 'SET', 'MIX', 'GETRANGE', 'SETRANGE', 'APPEND', 'INCR', 'MGET8', 'MSET8'):
        if name == 'INCR':
            init = [op(('SET', KEY, '0'), Status(), primary=False)]
            cycle = [op(('INCR', KEY), 1, 'positive')]
        elif name == 'APPEND':
            cycle = [op(('APPEND', KEY, 'x'), size + 1, 'positive')]
            note = 'One-byte append; strings grow for the bounded window.'
        elif name == 'MIX':
            cycle = [op(('GET', KEY), v), op(('SET', KEY, v), Status())]
        elif name == 'GET':
            cycle = [op(('GET', KEY), v)]
        elif name == 'SET':
            cycle = [op(('SET', KEY, v), Status())]
        elif name == 'GETRANGE':
            cycle = [op(('GETRANGE', KEY, 0, 9), v[:10])]
        elif name == 'SETRANGE':
            cycle = [op(('SETRANGE', KEY, 0, 'x'), size)]
        else:
            # Eight distinct key namespaces, each with exactly the same population.
            # Eight namespaces make these eight distinct keys even at one-key smoke size.
            keys = [KEY.replace('sv:', f's{i}:') for i in range(8)]
            init = [op(('SET', k, v), Status(), primary=False) for k in keys]
            cycle = [op(('MGET', *keys), [v] * 8)] if name == 'MGET8' else [
                op(('MSET', *(x for k in keys for x in (k, v))), Status())]
            key_multiplier = 8
    elif name.startswith('H'):
        shape = 'hash'
        init = [op(('HSET', KEY, *(x for i in range(n) for x in (field(i), '0'))), n, primary=False)]
        if name == 'HSET':
            cycle = [op(('HSET', KEY, field(0), '0'), 0)]
        elif name == 'HGET':
            cycle = [op(('HGET', KEY, field(0)), b'0')]
        elif name == 'HMGET8':
            cycle = [op(('HMGET', KEY, *(field(i) for i in range(8))), [b'0'] * 8)]
        elif name == 'HGETALL':
            cycle = [op(('HGETALL', KEY), [x for i in range(n) for x in (field(i), b'0')], 'pairs')]
        elif name == 'HINCRBY':
            cycle = [op(('HINCRBY', KEY, field(0), 1), 1, 'positive')]
    elif name in ('LPUSH', 'RPOP', 'LPUSH_RPOP', 'LRANGE10', 'LRANGE100', 'LINDEX'):
        shape = 'list'
        init = [op(('RPUSH', KEY, *([v] * n)), n, primary=False)]
        if name == 'LPUSH':
            cycle = [op(('LPUSH', KEY, v), n + 1, 'positive')]
            note = 'Lists grow for the bounded window.'
        elif name in ('RPOP', 'LPUSH_RPOP'):
            # Push-before-pop keeps every RPOP nonempty even with shared keys.
            cycle = [op(('LPUSH', KEY, v), n + 1, 'positive', name == 'LPUSH_RPOP'), op(('RPOP', KEY), v)]
            note = 'RPOP includes a counted LPUSH refill; LPUSH_RPOP counts both commands.'
        elif name == 'LINDEX':
            cycle = [op(('LINDEX', KEY, 5), v)]
        else:
            length = 10 if name == 'LRANGE10' else 100
            cycle = [op(('LRANGE', KEY, 0, length - 1), [v] * min(n, length))]
    elif name in ('SADD', 'SISMEMBER', 'SMEMBERS', 'SINTER'):
        shape = 'set'
        members = [member(i) for i in range(n)]
        init = [op(('SADD', KEY, *members), n, primary=False)]
        if name == 'SADD':
            cycle = [op(('SADD', KEY, members[0]), 0)]
        elif name == 'SISMEMBER':
            cycle = [op(('SISMEMBER', KEY, members[0]), 1)]
        else:
            if name == 'SINTER':
                init += [op(('SADD', OTHER, *members), n, primary=False)]
                key_multiplier = 2
            cycle = [op((name, KEY, OTHER) if name == 'SINTER' else (name, KEY), members, 'unordered')]
    elif name.startswith('Z'):
        shape = 'zset'
        init = [op(('ZADD', KEY, *(x for i in range(n) for x in (i, member(i)))), n, primary=False)]
        if name == 'ZADD':
            cycle = [op(('ZADD', KEY, 0, member(0)), 0)]
        elif name == 'ZINCRBY':
            cycle = [op(('ZINCRBY', KEY, 1, member(0)), b'1', 'number')]
        elif name == 'ZRANGE':
            cycle = [op(('ZRANGE', KEY, 0, 9, 'WITHSCORES'), [x for i in range(10) for x in (member(i), str(i))])]
        elif name == 'ZRANGEBYSCORE':
            cycle = [op(('ZRANGEBYSCORE', KEY, 0, 9), [member(i) for i in range(10)])]
        elif name == 'ZRANK':
            cycle = [op(('ZRANK', KEY, member(n // 2)), n // 2)]
    elif name in ('XADD', 'XRANGE', 'XREADGROUP'):
        shape = 'stream'
        init = [op(('XADD', STREAM, f'{i + 1}-0', 'f', 'v'), f'{i + 1}-0', primary=False) for i in range(10)]
        entries = [[f'{i + 1}-0', ['f', 'v']] for i in range(10)]
        if name == 'XADD':
            # Fixed explicit ID plus reset keeps sidecar byte-for-byte deterministic.
            cycle = [op(('DEL', STREAM), 1, primary=False), op(('XADD', STREAM, '1-0', 'f', 'v'), '1-0')]
            note = 'XADD into a fresh stream, with DEL reset counted as auxiliary work.'
        elif name == 'XRANGE':
            cycle = [op(('XRANGE', STREAM, '-', '+', 'COUNT', 10), entries)]
        else:
            init += [op(('XGROUP', 'CREATE', STREAM, 'g', '0'), Status(), primary=False)]
            cycle = [op(('XGROUP', 'SETID', STREAM, 'g', '0'), Status(), primary=False),
                     op(('XREADGROUP', 'GROUP', 'g', 'c', 'COUNT', 10, 'STREAMS', STREAM, '>'), [[STREAM, entries]]),
                     op(('XACK', STREAM, 'g', *(f'{i + 1}-0' for i in range(10))), 10)]
            note = 'Ten fixed entries replayed via XGROUP SETID; XREADGROUP and XACK are primary commands.'
    elif name in ('SETBIT', 'BITCOUNT'):
        shape = 'bitmap'
        init = [op(('SET', KEY, b'\xff' * size), Status(), primary=False)]
        cycle = [op(('SETBIT', KEY, 7, 1), 1)] if name == 'SETBIT' else [op(('BITCOUNT', KEY), size * 8)]
    elif name in ('PFADD', 'PFCOUNT'):
        shape = 'hll'
        init = [op(('PFADD', KEY, 'member'), 1, primary=False)]
        cycle = [op(('PFADD', KEY, 'member'), 0)] if name == 'PFADD' else [op(('PFCOUNT', KEY), 1)]
    elif name in ('GEOADD', 'GEOSEARCH'):
        shape = 'geo'
        init = [op(('GEOADD', KEY, 121.5, 25.0, 'taipei'), 1, primary=False)]
        cycle = [op(('GEOADD', KEY, 121.5, 25.0, 'taipei'), 0)] if name == 'GEOADD' else [
            op(('GEOSEARCH', KEY, 'FROMMEMBER', 'taipei', 'BYRADIUS', 1, 'km'), ['taipei'])]
    require(cycle, f'unknown workload {name}')
    # memtier fits independent single-key commands. The native driver handles
    # coupled/refill cycles, explicit stream IDs, eight distinct key namespaces,
    # and payloads exceeding Linux's per-argument limit. All offered-load cells
    # use native so individual scheduled/sent/completed timestamps survive.
    engine = 'memtier' if len(cycle) == 1 and name not in ('MGET8', 'MSET8', 'XRANGE', 'SINTER') and len(encode(*cycle[0]['command'])) < 120000 else 'native'
    return dict(name=name, shape=shape, size=size, cardinality=n, init=init, cycle=cycle,
                multiplier=key_multiplier, engine=engine, note=note,
                primary_per_cycle=sum(row['primary'] for row in cycle))


def command_cells(args):
    cells = []
    groups = {
        'strings': [(x, 100) for x in ('GET', 'SET', 'INCR', 'APPEND', 'GETRANGE', 'SETRANGE', 'MGET8', 'MSET8')],
        'hashes': [(x, 10) for x in ('HSET', 'HGET', 'HMGET8', 'HGETALL', 'HINCRBY')] + [('HGETALL', 100)],
        'lists': [(x, 100) for x in ('LPUSH', 'RPOP', 'LRANGE10', 'LRANGE100', 'LINDEX')],
        'sets': [(x, 10) for x in ('SADD', 'SISMEMBER', 'SMEMBERS', 'SINTER')] + [('SMEMBERS', 100)],
        'zsets': [(x, n) for n in (100, 10000) for x in ('ZADD', 'ZINCRBY', 'ZRANGE', 'ZRANGEBYSCORE', 'ZRANK')],
        'streams': [(x, 10) for x in ('XADD', 'XRANGE', 'XREADGROUP')],
        'bitmap_hll': [(x, 100) for x in ('SETBIT', 'BITCOUNT', 'PFADD', 'PFCOUNT')],
        'geo': [(x, 100) for x in ('GEOADD', 'GEOSEARCH')],
    }
    for family in select(args.families, groups):
        for cmd, card in groups[family]:
            for pipeline in numbers(args.pipelines):
                w = workload(cmd, cardinality=card)
                cells.append(dict(name=f'{family}-{cmd}-n{card}-p{pipeline}', family=family, workload=w,
                                  pipeline=pipeline, keys=args.keys, connections=args.connections))
    return cells


def select(raw, allowed):
    values = list(allowed) if raw == 'all' else raw.split(',')
    require(values and len(set(values)) == len(values) and set(values) <= set(allowed), f'invalid selection {raw}')
    return values


def numbers(raw):
    values = [int(x) for x in raw.split(',')]
    require(values and min(values) > 0 and len(set(values)) == len(values), 'invalid numeric list')
    return values


def parser(description, all_variants=False):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--candidate', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--redis', type=Path, default=Path('/home/user/Projects/redis74/src/redis-server'))
    p.add_argument('--client', type=Path, default=ROOT / 'build/survey-client')
    p.add_argument('--memtier', type=Path, default=Path(shutil.which('memtier_benchmark') or '/usr/bin/memtier_benchmark'))
    p.add_argument('--output', type=Path)
    p.add_argument('--server-cores', default='48-55')
    p.add_argument('--load-cores', default='56-63')
    p.add_argument('--port', type=int, default=20400)
    p.add_argument('--variants', default='1s-rl0,1s-rl1,2s-rl0,2s-rl1' if all_variants else '2s-rl0')
    p.add_argument('--redis-threads', default='1,4' if all_variants else '4')
    p.add_argument('--blocks', type=int, default=3)
    p.add_argument('--seconds', type=float, default=15)
    p.add_argument('--keys', type=int, default=1024)
    p.add_argument('--connections', type=int, default=512)
    p.add_argument('--workers', type=int, default=-1, help='-1: one native worker per load CPU, at most connections; positive: explicit limit')
    p.add_argument('--timeout', type=float, default=120)
    p.add_argument('--ratio', help='default 3:1 split, using all server CPUs')
    p.add_argument('--shards', type=int, default=256)
    p.add_argument('--sidecar-samples', type=int, default=3, help='per workload, on a separate fresh boot')
    p.add_argument('--disk-limit-gib', type=float, default=12, help='owned per-boot persistence data budget; abort if exceeded')
    return p


def configure(args):
    require(args.output, '--output is required')
    args.output = args.output.resolve()
    require(not args.output.exists(), 'output directory must be new')
    server, load = cpus(args.server_cores), cpus(args.load_cores)
    require(not set(server) & set(load), 'server/load CPUs overlap')
    require(set(server + load) <= set(range(os.cpu_count())), 'CPU outside machine')
    if args.smoke:
        require(set(server + load) <= set(range(48, 64)), 'smokes must use CPUs 48-63 only')
        args.blocks, args.seconds = 1, 2.0
        args.keys, args.connections = min(args.keys, 32), min(args.connections, 4)
        args.workers = min(args.workers if args.workers > 0 else 2, 2)
        args.shards = 16
    require(20400 <= args.port <= 20499, 'survey port must be 20400-20499')
    require(args.blocks > 0 and args.seconds > 0 and args.timeout > 0 and args.keys > 0 and args.connections > 0,
            'invalid duration/population/connections')
    require(args.workers == -1 or 1 <= args.workers <= len(load), 'workers must be -1 or a positive count within load CPUs')
    require(args.sidecar_samples > 0, 'sidecar sample count must be positive')
    require(0 < args.disk_limit_gib <= 12, 'persistence budget must be in (0,12] GiB')
    if args.ratio is None:
        require(len(server) % 4 == 0, 'automatic ratio requires server CPU count divisible by four')
        args.ratio = f'{len(server) * 3 // 4}:{len(server) // 4}'
    ratio = [int(x) for x in args.ratio.split(':')]
    require(len(ratio) == 2 and min(ratio) > 0 and sum(ratio) == len(server), 'ratio does not use all server CPUs')
    select(args.variants, ('1s-rl0', '1s-rl1', '2s-rl0', '2s-rl1'))
    require(set(numbers(args.redis_threads)) <= {1, 4}, 'Redis io-threads must be 1 or 4')
    os.sched_setaffinity(0, load)
    for attr in ('candidate', 'redis', 'client', 'memtier'):
        path = getattr(args, attr).resolve()
        require(path.is_file() and os.access(path, os.X_OK), f'missing executable {path}; see survey-plan.md')
        setattr(args, attr, path)
    version = subprocess.check_output([str(args.redis), '--version'], text=True).strip()
    require('v=7.4.' in version, 'reference is not Redis 7.4')
    args.output.mkdir(parents=True)
    save(args.output / 'manifest.json', dict(args=vars(args), redis_version=version,
         binaries={k: dict(path=str(getattr(args, k)), sha256=fm.sha256(getattr(args, k))) for k in ('candidate', 'redis', 'client', 'memtier')},
         memtier_version=subprocess.check_output([str(args.memtier), '--version'], text=True).strip(),
         source_sha=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
         kind='SMOKE_ONLY' if args.smoke else 'SURVEY', latency_unit='ns', histogram_significant_digits=3))


def server_argv(args, arm, folder, persistence='off'):
    redis = arm.startswith('redis')
    argv = ['taskset', '-c', args.server_cores, str(args.redis if redis else args.candidate),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(folder / 'data'),
            '--save', '', '--databases', '1', '--maxclients', '20064', '--appendonly',
            'yes' if persistence in ('everysec', 'always') else 'no', '--appendfsync',
            persistence if persistence in ('everysec', 'always') else 'everysec',
            '--auto-aof-rewrite-percentage', '0']
    if redis:
        argv += ['--io-threads', arm.split('-')[-1], '--io-threads-do-reads', 'yes']
    else:
        mode, rl = arm.split('-')
        argv += ['--thread-mode', mode, '--read-local', rl[-1], '--shards', str(args.shards),
                 '--atomic', '1', '--key-lb', '0', '--client-lb', '0']
        if mode == '2s':
            argv += ['--ratio', args.ratio, '--flip-auto', '0']
    return argv


@contextlib.contextmanager
def server(args, arm, folder, persistence='off'):
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / 'data'
    data.mkdir()
    fm.free_port(args.port)
    command = server_argv(args, arm, folder, persistence)
    save(folder / 'server-argv.json', command)
    conn = process = None
    monitor_stop, disk_failure = threading.Event(), []
    monitor = None
    try:
        with (folder / 'server.log').open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=folder,
                                       env=dict(os.environ, LC_ALL='C'), start_new_session=True)
            def disk_watch():
                while not monitor_stop.wait(.1):
                    try:
                        used = sum(path.stat().st_size for path in data.rglob('*') if path.is_file())
                    except FileNotFoundError:
                        continue  # rename during snapshot/AOF publication
                    if used > args.disk_limit_gib * 1024 ** 3:
                        disk_failure.append(f'owned persistence data exceeded {args.disk_limit_gib} GiB')
                        process.terminate()
                        return
            if persistence != 'off':
                monitor = threading.Thread(target=disk_watch, daemon=True)
                monitor.start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                require(process.poll() is None, f'server boot failed: {folder}/server.log')
                try:
                    conn = Resp(args.port, 1)
                    require(conn.cmd('PING') == b'PONG', 'bad PING')
                    break
                except OSError:
                    if conn:
                        conn.close()
                        conn = None
                    time.sleep(.05)
            require(conn is not None, 'server boot timed out')
            conn.sock.settimeout(args.timeout)
            boot = fm.info(conn)
            require(int(boot['process_id']) == process.pid, 'listener PID is not our child')
            if not arm.startswith('redis'):
                mode, rl = arm.split('-')
                require(boot.get('thread_mode') == mode and boot.get('read_local') == rl[-1], 'wrong TomoKV mode')
                require(int(boot['shards']) == args.shards, 'wrong shard count')
            for key, value in (('appendonly', 'yes' if persistence in ('always', 'everysec') else 'no'),
                               ('appendfsync', persistence if persistence in ('always', 'everysec') else 'everysec'),
                               ('databases', '1')):
                require(conn.cmd('CONFIG', 'GET', key) == [key.encode(), value.encode()], f'wrong config {key}')
            if arm.startswith('redis'):
                require(conn.cmd('CONFIG', 'GET', 'io-threads') == [b'io-threads', arm.split('-')[-1].encode()], 'wrong Redis threads')
            require(conn.cmd('DBSIZE') == 0, 'fresh boot contains keys')
            save(folder / 'boot-info.json', boot)
            yield process, conn
            require(not disk_failure, '; '.join(disk_failure))
            require(process.poll() is None, 'server exited during run')
    finally:
        monitor_stop.set()
        if monitor:
            monitor.join(timeout=2)
        if disk_failure:
            save(folder / 'disk-budget-failure.json', disk_failure)
        if conn:
            conn.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if process:
            save(folder / 'server-exit.json', dict(returncode=process.returncode))
        # The owned per-boot data directory is never reused or retained, even on failure.
        shutil.rmtree(data)
    require(process.returncode == 0, f'server teardown failed: {process.returncode}')


def command_name(command):
    name = str(command[0]).lower()
    return name + '|' + str(command[1]).lower() if name == 'xgroup' else name


def calls(info, name):
    raw = info.get('cmdstat_' + name)
    if raw is None:
        return 0
    fields = dict(x.split('=', 1) for x in raw.split(','))
    return int(fields['calls'])


def accounting(before, after, counts):
    counts = Counter(counts)
    # Redis subdivides XGROUP by subcommand; TomoKV exposes the registered
    # parent command. Aggregate only that documented INFO representation.
    if 'thread_mode' in after:
        mapped = Counter()
        for name, n in counts.items():
            mapped[name.split('|')[0]] += n
        counts = mapped
    delta = {}
    for key in COUNTERS:
        require((key in before) == (key in after), f'disappearing INFO {key}')
        if key not in before:
            require(key not in ('total_commands_processed', 'total_error_replies', 'expired_keys', 'evicted_keys', 'rejected_connections'), f'missing INFO {key}')
            delta[key] = None
        else:
            delta[key] = int(after[key]) - int(before[key])
            require(delta[key] >= 0, f'counter reset {key}')
            if key in ZERO:
                require(delta[key] == 0, f'nonzero {key}: {delta[key]}')
    evidence = {}
    for name, count in counts.items():
        observed = calls(after, name) - calls(before, name)
        require(observed == count, f'INFO {name}: {observed} calls != {count} validated completions')
        evidence[name] = observed
    # No client besides the harness/load is admitted. INFO and persistence
    # controller commands are excluded; every other command must be accounted.
    for key in set(before) | set(after):
        if key.startswith('cmdstat_'):
            name = key[8:]
            if name not in counts and name not in ('info', 'bgsave'):
                require(calls(after, name) == calls(before, name), f'unaccounted command {name}')
    return dict(counters=delta, commands=evidence)


def histogram(rows, field):
    bins, maximum, count = Counter(), 0, 0
    for row in rows:
        h = row[field]
        require(h['n'] > 0 and sum(v for _, v in h['bins']) == h['n'], 'histogram count mismatch')
        require(all(isinstance(edge, int) and edge >= 0 and isinstance(n, int) and n > 0 for edge, n in h['bins']), 'invalid histogram bin')
        bins.update(dict(h['bins']))
        maximum, count = max(maximum, h['max']), count + h['n']
    require(count > 0, 'empty histogram')
    def percentile(q):
        target, total = math.ceil(q * count), 0
        for edge, n in sorted(bins.items()):
            total += n
            if total >= target:
                return edge
        raise Invalid('bad percentile')
    return dict(n=count, p50=percentile(.5), p99=percentile(.99), p999=percentile(.999), max=maximum,
                unit='ns', significant_digits=3, bins=sorted(bins.items()))


def validate_client(document, operations, seconds, offered=None, max_lag_ms=20, count=None):
    require(document.get('valid') is True and document['workers'], 'native client failed')
    rows = document['workers']
    counts = Counter()
    primary = sum(row['primary'] for row in rows)
    cycles = sum(row['cycles'] for row in rows)
    for row in rows:
        require(row['completed'] > 0 and len(row['counts']) == len(operations), 'inactive/incomplete worker')
        require(row['completed'] == sum(row['counts']), 'lost reply')
        require(all(n == row['cycles'] for n in row['counts']), 'partial cycle')
        require(row['primary'] == row['cycles'] * sum(op['primary'] for op in operations), 'wrong primary count')
        require(row['scheduled'] == row['primary'], 'dropped deadline')
        if row['primary']:
            require(all(row[field]['n'] == row['primary'] for field in ('rtt', 'response', 'lag')), 'per-worker observation loss')
        for operation, n in zip(operations, row['counts']):
            counts[command_name(operation['command'])] += n
    require(primary > 0 or count is not None, 'no primary completions')
    if count is not None:
        require(cycles == count, 'incomplete preload/delete population')
    elapsed = max((row['finish_ns'] - document['epoch_ns']) / 1e9 for row in rows)
    require(elapsed > 0, 'invalid client interval')
    if count is None and offered is None:
        require(elapsed >= seconds, 'short native throughput window')
    rate_interval = max(seconds, elapsed) if offered is not None else elapsed
    result = dict(completed=primary, cycles=cycles, commands=dict(counts), elapsed=elapsed,
                  client_epoch_ns=document['epoch_ns'],
                  engine='native',
                  ops_per_second=primary / rate_interval, total_command_rate=sum(counts.values()) / rate_interval,
                  worker_cpu_fraction=[row['cpu_seconds'] / elapsed for row in rows])
    if primary:
        result.update(latency=histogram(rows, 'rtt'), scheduled_latency=histogram(rows, 'response'),
                      schedule_lag=histogram(rows, 'lag'))
        require(all(result[key]['n'] == primary for key in ('latency', 'scheduled_latency', 'schedule_lag')), 'missing latency observations')
    if offered is not None:
        per_cycle = sum(op['primary'] for op in operations)
        expected = math.ceil(offered * seconds / per_cycle) * per_cycle
        require(primary == expected, f'offered count mismatch {primary} != {expected}')
        require(result['schedule_lag']['max'] <= max_lag_ms * 1e6, 'generator missed send deadlines')
        require(elapsed <= seconds + max_lag_ms / 1000 + result['latency']['max'] / 1e9 + .1, 'excessive drain')
    result['generator_busy'] = max(result['worker_cpu_fraction']) >= .95
    return result


def native(args, conn, folder, operations, keys, connections, pipeline=1, seconds=None, count=None,
           offered=None, raw=False, during=None):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'script.resp'
    write_script(path, operations)
    workers = min(len(cpus(args.load_cores)) if args.workers == -1 else args.workers, connections)
    seconds = seconds or args.seconds
    argv = ['taskset', '-c', args.load_cores, str(args.client), '--port', str(args.port), '--script', str(path),
            '--out', str(folder / 'client.json'), '--connections', str(connections), '--threads', str(workers),
            '--pipeline', str(pipeline), '--keys', str(keys), '--seconds', str(seconds), '--timeout', str(args.timeout),
            '--cpus', ','.join(map(str, cpus(args.load_cores))), '--ready', str(folder / 'ready'), '--go', str(folder / 'go')]
    if count is not None:
        argv += ['--count', str(count)]
    if offered is not None:
        argv += ['--rate', str(offered)]
    if raw:
        argv += ['--raw', str(folder / 'observations')]
    save(folder / 'client-argv.json', argv)
    process = None
    try:
        with (folder / 'client.log').open('wb') as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + args.timeout
            while not (folder / 'ready').exists():
                require(process.poll() is None, f'client failed before ready: {folder}/client.log')
                require(time.monotonic() < deadline, 'client connection setup timed out')
                time.sleep(.005)
            before = fm.info(conn)
            save(folder / 'info-before.json', before)
            (folder / 'go').touch()
            if during:
                during(process)
            require(process.wait(timeout=seconds + args.timeout + 10) == 0, f'client failed: {folder}/client.log')
            after = fm.info(conn)
            save(folder / 'info-after.json', after)
            document = json.loads((folder / 'client.json').read_text())
            result = validate_client(document, operations, seconds, offered, getattr(args, 'max_lag_ms', 20), count)
            result['info_delta'] = accounting(before, after, result['commands'])
            if raw:
                raw_files, observations = [], 0
                for path in sorted(folder.glob('observations.*.bin')):
                    require(path.stat().st_size % 32 == 0, 'truncated raw observation')
                    observations += path.stat().st_size // 32
                    compressed = path.with_suffix('.bin.gz')
                    with path.open('rb') as source, gzip.open(compressed, 'wb', compresslevel=1) as dest:
                        shutil.copyfileobj(source, dest)
                    raw_files.append(dict(path=str(compressed), sha256=fm.sha256(compressed)))
                    path.unlink()
                require(observations == result['completed'], 'raw observation loss')
                result['observations'] = dict(files=raw_files, count=observations,
                    format='little-endian uint64[4]: connection_id, scheduled_ns, sent_ns, completion_ns; times relative to client epoch')
            save(folder / 'result.json', result)
            return result
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def seed(args, conn, folder, cell):
    w, keys = cell['workload'], cell['keys']
    if w['name'] in ('XADD', 'XREADGROUP'):
        require(keys >= cell['connections'] and keys % cell['connections'] == 0,
                'stateful stream cells require disjoint per-connection key ranges: keys must be a multiple of connections')
    require(conn.cmd('DBSIZE') == 0, 'preload requires empty image')
    result = native(args, conn, folder / 'seed', w['init'], keys, min(32, keys), pipeline=8,
                    count=keys, seconds=max(args.timeout, 3600))
    require(conn.cmd('DBSIZE') == keys * w['multiplier'], 'wrong preload DBSIZE')
    save(folder / 'preload.json', dict(keys=keys, logical_keys=keys * w['multiplier'],
         shape=w['shape'], value_bytes=w['size'], cardinality=w['cardinality'], result=result))


def memtier_command(operation):
    parts = []
    for value in operation['command']:
        if value == KEY:
            parts.append('__key__')
        else:
            value = value.decode('ascii') if isinstance(value, bytes) else str(value)
            require(value and not any(ch.isspace() or ch in "'\"\\" for ch in value), 'unsafe memtier command argument')
            parts.append(value)
    return ' '.join(parts)


def memtier_result(data, operation, connections, pipeline, seconds):
    stats, name = data['ALL STATS'], command_name(operation['command'])
    runtime, totals = stats['Runtime'], stats['Totals']
    require(runtime['Interrupted'] in (False, 'false'), 'memtier interrupted')
    require(runtime['Time unit'] == 'MILLISECONDS', 'unknown memtier runtime unit')
    elapsed = runtime['Total duration'] / 1000
    require(elapsed >= seconds and elapsed <= seconds + 30, 'short/excessive memtier interval')
    require({'Connection Errors', 'Connection Errors/sec'} <= totals.keys(), 'memtier missing connection error counters')
    for key in ('Errors', 'Errors/sec', 'Connection Errors', 'Connection Errors/sec'):
        require(float(totals.get(key, 0)) == 0, f'memtier nonzero {key}')
    candidates = [row for key, row in stats.items() if key.lower() in (name, name + 's')]
    require(len(candidates) == 1, 'missing custom-command histogram')
    row = candidates[0]
    bins_us = decode_histogram(row['Percentile Latencies']['Histogram log format']['Compressed Histogram'])
    completed = sum(bins_us.values())
    require(completed > 0 and row['Count'] == totals['Count'], 'bad memtier command count')
    # memtier's reported Count can omit its final finite in-flight batch. The
    # drained HDR count must EXACTLY match INFO; the gate uses the same contract.
    require(abs(row['Count'] - completed) <= connections * pipeline, 'memtier Count/HDR discrepancy exceeds outstanding work')
    h = dict(n=completed, max=max(bins_us) * 1000, bins=[[us * 1000, n] for us, n in bins_us.items()])
    latency = histogram([dict(h=h)], 'h')
    latency['max_kind'] = 'HDR upper equivalent (memtier does not retain exact raw max)'
    return dict(completed=completed, commands={name: completed}, elapsed=elapsed,
                ops_per_second=completed / elapsed, total_command_rate=completed / elapsed,
                latency=latency, generator_busy=False, generator_busy_basis='per-worker CPU sampled during memtier lifetime',
                memtier_reported_count=row['Count'], memtier_count_hdr_bound=connections * pipeline,
                engine='memtier --command', runtime=runtime)


def memtier(args, conn, folder, cell):
    folder.mkdir(parents=True)
    seconds = cell.get('seconds', args.seconds)
    require(seconds == int(seconds), 'memtier --test-time needs integer seconds')
    operations = cell['workload']['cycle']
    require(len(operations) == 1 and operations[0]['primary'], 'memtier requires one primary command')
    connections = cell['connections']
    limit = min(len(cpus(args.load_cores)) if args.workers == -1 else args.workers, connections)
    threads = max(n for n in range(1, limit + 1) if connections % n == 0)
    argv = ['taskset', '-c', args.load_cores, str(args.memtier), '--server=127.0.0.1', f'--port={args.port}',
            '--protocol=redis', f'--threads={threads}', f'--clients={connections // threads}',
            f'--pipeline={cell["pipeline"]}', f'--test-time={int(seconds)}', '--key-prefix=sv:',
            '--key-minimum=100000000000', f'--key-maximum={100000000000 + cell["keys"] - 1}',
            '--hide-histogram', f'--json-out-file={folder / "memtier.json"}',
            '--command=' + memtier_command(operations[0]), '--command-key-pattern=R']
    save(folder / 'client-argv.json', argv)
    before = fm.info(conn)
    save(folder / 'info-before.json', before)
    process, cpu_samples = None, {}
    started = time.monotonic()
    try:
        with (folder / 'client.log').open('wb') as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                now = time.monotonic()
                require(now - started < seconds + args.timeout, 'memtier timed out')
                for path in Path(f'/proc/{process.pid}/task').glob('*/stat'):
                    try:
                        fields = path.read_text().rsplit(')', 1)[1].split()
                        ticks = int(fields[11]) + int(fields[12])
                        cpu_samples.setdefault(path.parent.name, []).append((now, ticks))
                    except FileNotFoundError:
                        pass
                time.sleep(.05)
            require(process.returncode == 0, f'memtier failed: {folder}/client.log')
        after = fm.info(conn)
        save(folder / 'info-after.json', after)
        result = memtier_result(json.loads((folder / 'memtier.json').read_text()), operations[0], connections, cell['pipeline'], seconds)
        hz = os.sysconf('SC_CLK_TCK')
        fractions = [(samples[-1][1] - samples[0][1]) / hz / (samples[-1][0] - samples[0][0])
                     for samples in cpu_samples.values() if len(samples) >= 3 and samples[-1][0] - samples[0][0] >= seconds * .8]
        require(len(fractions) >= threads, 'missing per-worker CPU samples')
        result.update(worker_cpu_fraction=fractions, generator_busy=max(fractions) >= .95)
        result['info_delta'] = accounting(before, after, result['commands'])
        require(result['info_delta']['counters']['keyspace_misses'] == 0, 'memtier hit workload missed keys')
        save(folder / 'result.json', result)
        return result
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def paired_ratios(records):
    groups = {}
    for row in records:
        if row.get('valid') and 'ops_per_second' in row:
            groups.setdefault((row['cell'], row['pair'], row['block']), []).append(row)
    out = []
    for (cell, pair, block), rows in groups.items():
        require(len(rows) == 4 and [r['letter'] for r in rows] == list('ABBA'), 'incomplete ABBA block')
        rates = {a: [r['ops_per_second'] for r in rows if r['letter'] == a] for a in 'AB'}
        means = {a: statistics.mean(v) for a, v in rates.items()}
        require(means['A'] > 0, 'zero reference throughput')
        spread = {a: (max(v) - min(v)) / means[a] * 100 for a, v in rates.items()}
        out.append(dict(cell=cell, pair=pair, block=block, tomo_over_redis=means['B'] / means['A'],
                        means=means, spread_percent=spread, stable=max(spread.values()) <= 2,
                        generator_busy=any(r['generator_busy'] for r in rows),
                        interpretable=max(spread.values()) <= 2 and not any(r['generator_busy'] for r in rows)))
    return out


def sidecar(args, cells):
    """Separate fresh sample boots; never contaminate a timed image or INFO interval."""
    unique = {}
    for cell in cells:
        w = cell['workload']
        unique.setdefault((w['name'], w['size'], w['cardinality']), w)
    refs = {}
    samples_path, differences = args.output / 'behaviour-samples.jsonl', args.output / 'behaviour-differences.jsonl'
    samples_path.touch()
    differences.touch()
    total = diffs = 0
    for arm in ['redis-4'] + select(args.variants, ('1s-rl0', '1s-rl1', '2s-rl0', '2s-rl1')):
        folder = args.output / 'sidecar' / arm
        with server(args, arm, folder) as (_, conn):
            for spec, w in unique.items():
                require(conn.cmd('FLUSHDB') == b'OK', 'sidecar reset failed')
                for row in w['init']:
                    wire = conn.wire(row['command'])
                    require(not wire.startswith(b'-'), f'sidecar preload error: {wire!r}')
                for sample in range(args.sidecar_samples):
                    for index, row in enumerate(w['cycle']):
                        actual = conn.wire(row['command'])
                        key = (spec, sample, index)
                        record = dict(arm=arm, workload=spec, sample=sample, command=[
                            x.decode(errors='backslashreplace') if isinstance(x, bytes) else x for x in row['command']],
                            wire_base64=base64.b64encode(actual).decode(), bytes=len(actual), primary=row['primary'])
                        if arm.startswith('redis'):
                            refs[key] = actual
                        else:
                            record['equal'] = actual == refs[key]
                            total += 1
                            if not record['equal']:
                                diffs += 1
                                append(differences, dict(record, redis_wire_base64=base64.b64encode(refs[key]).decode(),
                                     note='Raw byte difference; unordered collections may legally differ in order. No normalization.'))
                        append(samples_path, record)
    return dict(comparisons=total, differences=diffs, samples=str(samples_path), difference_file=str(differences))


def run_throughput(args, cell, arm, folder):
    with server(args, arm, folder, cell.get('persistence', 'off')) as (_, conn):
        seed(args, conn, folder, cell)
        if cell['workload']['engine'] == 'memtier':
            return memtier(args, conn, folder / 'load', cell)
        return native(args, conn, folder / 'load', cell['workload']['cycle'], cell['keys'],
                      cell['connections'], cell['pipeline'], seconds=cell.get('seconds'))


def summary(tool, records, expected, smoke=False, error=None):
    valid = error is None and len(records) == expected and expected > 0 and all(r.get('valid') for r in records)
    line = f'{tool}: status={"VALID" if valid else "INVALID"} kind={"SMOKE_ONLY" if smoke else "SURVEY"} runs={len(records)}/{expected}'
    return line, valid


def campaign(args, tool, build_cells, runner=run_throughput, prepare=None, finish=None, behaviour_cells=None):
    records, error, expected, owns_output = [], None, 0, False
    try:
        configure(args)
        owns_output = True
        selected = build_cells(args)
        require(selected, 'empty survey')
        save(args.output / 'cells.json', selected)
        if prepare:
            prepare(args, selected)
        behavior = sidecar(args, behaviour_cells(args) if behaviour_cells else selected)
        save(args.output / 'behaviour.json', behavior)
        variants = select(args.variants, ('1s-rl0', '1s-rl1', '2s-rl0', '2s-rl1'))
        pairs = [(f'redis-{r}', v) for r in numbers(args.redis_threads) for v in variants]
        expected = len(selected) * len(pairs) * args.blocks * 4
        for block in range(args.blocks):
            for cell in selected:
                for redis, tomo in pairs:
                    pair = f'{tomo}_vs_{redis}'
                    for seq, letter in enumerate('ABBA'):
                        arm = redis if letter == 'A' else tomo
                        folder = args.output / cell['name'] / pair / f'b{block}-{seq}-{letter}'
                        row = dict(cell=cell['name'], pair=pair, block=block, sequence=seq, letter=letter,
                                   arm=arm, valid=False, folder=str(folder))
                        try:
                            row.update(runner(args, cell, arm, folder))
                            row['valid'] = True
                        except (Exception, KeyboardInterrupt) as exc:
                            row['error'] = f'{type(exc).__name__}: {exc}'
                            raise
                        finally:
                            records.append(row)
                            folder.mkdir(parents=True, exist_ok=True)
                            save(folder / 'record.json', row)
                            append(args.output / 'records.jsonl', row)
                            metrics = ''
                            if not args.smoke and row['valid']:
                                if 'ops_per_second' in row:
                                    h = row['latency']
                                    metrics = f' ops_s={row["ops_per_second"]:.3f} p50_ns={h["p50"]} p99_ns={h["p99"]} p999_ns={h["p999"]} max_ns={h["max"]}'
                                elif 'loaded' in row:
                                    metrics = f' used_B_per_key={row["loaded"]["used_memory_per_key"]:.3f} rss_B_per_key={row["loaded"]["rss_per_key"]:.3f} half_rss_B_per_key={row["after_half_del"]["rss_per_key"]:.3f}'
                            print(f'{tool}: cell={cell["name"]} block={block} visit={seq} arm={arm} status={"VALID" if row["valid"] else "INVALID"} kind={"SMOKE_ONLY" if args.smoke else "SURVEY"}{metrics}', flush=True)
        save(args.output / 'ratios.json', paired_ratios(records))
        if finish:
            finish(args, records)
        manifest = json.loads((args.output / 'manifest.json').read_text())
        for key, value in manifest['binaries'].items():
            require(fm.sha256(getattr(args, key)) == value['sha256'], f'{key} binary changed')
    except (Exception, KeyboardInterrupt) as exc:
        error = f'{type(exc).__name__}: {exc}'
        print(error, file=sys.stderr, flush=True)
    line, valid = summary(tool, records, expected, args.smoke, error)
    if owns_output:
        save(args.output / 'verdict.json', dict(valid=valid, error=error, summary=line))
        (args.output / 'summary.txt').write_text(line + '\n')
    print(line, flush=True)
    return 0 if valid else 1


def rejects(function):
    try:
        function()
    except (Invalid, ValueError, KeyError):
        return
    raise AssertionError('poisoned evidence was accepted')


def base_selftest():
    # Exact wire preservation, including error and array order, on mocked sockets.
    c = Resp.__new__(Resp)
    wire = b'*2\r\n$1\r\na\r\n-ERR test\r\n'
    c.file = io.BytesIO(wire)
    assert c.read_wire() == wire
    c.file = io.BytesIO(b'$3\r\nab')
    rejects(c.read_wire)
    h = dict(n=1000, max=10000, bins=[[10, 990], [100, 9], [10000, 1]])
    pooled = histogram([dict(h=h), dict(h=h)], 'h')
    assert (pooled['n'], pooled['p50'], pooled['p99'], pooled['p999'], pooled['max']) == (2000, 10, 10, 100, 10000)
    rejects(lambda: histogram([dict(h=dict(h, n=999))], 'h'))
    before = {key: '0' for key in COUNTERS}
    after = dict(before, total_commands_processed='10', cmdstat_get='calls=10,usec=0')
    assert accounting(before, after, {'get': 10})['commands']['get'] == 10
    for poison in (dict(cmdstat_get='calls=9'), dict(total_error_replies='1'), dict(evicted_keys='1'), dict(total_commands_processed='-1')):
        rejects(lambda: accounting(before, dict(after, **poison), {'get': 10}))
    rows = [dict(valid=True, cell='x', pair='p', block=0, letter=a, ops_per_second=r, generator_busy=False)
            for a, r in zip('ABBA', (10, 20, 20, 10))]
    assert paired_ratios(rows)[0]['tomo_over_redis'] == 2
    rejects(lambda: paired_ratios(rows[:-1]))
    assert summary('test', rows, 4)[1] and not summary('test', rows, 5)[1]
    assert not summary('test', rows, 4, error='failure')[1]
    for cmd in ('MGET8', 'RPOP', 'SINTER', 'XREADGROUP', 'GEOSEARCH'):
        w = workload(cmd)
        assert w['cycle'] and w['init'] and w['primary_per_cycle'] > 0
    assert memtier_command(workload('GET')['cycle'][0]) == 'GET __key__'
    s = {'Runtime': {'Interrupted': False, 'Time unit': 'MILLISECONDS', 'Total duration': 1000},
         'Totals': {'Count': 10, 'Connection Errors': 0, 'Connection Errors/sec': 0},
         'Gets': {'Count': 10, 'Percentile Latencies': {'Histogram log format': {'Compressed Histogram': 'mock'}}}}
    with patch(__name__ + '.decode_histogram', return_value={10: 10}):
        result = memtier_result({'ALL STATS': s}, workload('GET')['cycle'][0], 1, 1, 1)
        assert result['completed'] == 10 and result['latency']['p999'] == 10000
        for location, key, value in (('Totals', 'Connection Errors', 1), ('Runtime', 'Interrupted', True),
                                     ('Runtime', 'Total duration', 500), ('Gets', 'Count', 3)):
            bad = copy.deepcopy(s)
            bad[location][key] = value
            rejects(lambda: memtier_result({'ALL STATS': bad}, workload('GET')['cycle'][0], 1, 1, 1))
