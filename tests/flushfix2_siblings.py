#!/usr/bin/env python3
"""Directed FLUSH siblings and liveness, using the same Redis 7.4 oracle.

DEBUG reload cases deliberately return failure on a missing/torn observation.
Those are witnesses for the separate database-boundary repair, not green rows.
"""
import contextlib
import json
from pathlib import Path
import shutil
import threading
import time

import flushfix2 as f
import snapfix as s
from _lib import Conn, RespError, encode

ORACLE = {}


def normalized(value):
    if isinstance(value, RespError):
        return value.message.decode()
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, list):
        return [normalized(x) for x in value]
    return value


@contextlib.contextmanager
def conn(b, args, db=0):
    c = Conn('127.0.0.1', b.port, timeout=args.stall)
    try:
        c.must('SELECT', db)
        yield c
    finally:
        c.close()


def semantics(args, directory, mode, engine, atomic, oracle):
    result = {}
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        c = b.c
        pair, _ = s.keys_for(c, 'flushfix2:sibling', oracle, 2)
        c.must('MSET', pair[0], 1, pair[1], 1)
        c.must('SCRIPT', 'FLUSH', 'SYNC')
        result['script_flush'] = c.must('MGET', *pair)
        c.must('FUNCTION', 'FLUSH', 'SYNC')
        result['function_flush'] = c.must('MGET', *pair)
        c.must('SCRIPT', 'FLUSH', 'ASYNC')
        result['script_flush_async'] = c.must('MGET', *pair)
        c.must('FUNCTION', 'FLUSH', 'ASYNC')
        result['function_flush_async'] = c.must('MGET', *pair)
        dumped = c.must('DUMP', pair[0])
        c.must('SET', pair[0], 2)
        c.must('RESTORE', pair[0], 0, dumped, 'REPLACE')
        result['restore_replace'] = c.must('MGET', *pair)
        if args.databases > 1:
            c.must('COPY', pair[0], pair[0], 'DB', 7, 'REPLACE')
            with conn(b, args, 7) as other:
                result['copy_db'] = [c.must('GET', pair[0]), other.must('GET', pair[0])]
                c.must('MOVE', pair[1], 7)
                result['move'] = [c.must('GET', pair[1]), other.must('GET', pair[1])]
        else:
            c.must('COPY', pair[0], 'flushfix2:copy:db0', 'DB', 0, 'REPLACE')
            result['copy_db'] = c.must('MGET', pair[0], 'flushfix2:copy:db0')
            result['move_same_db'] = c.cmd('MOVE', pair[1], 0)
        with conn(b, args) as watcher:
            watcher.must('WATCH', pair[0])
            c.must('FLUSHALL')
            watcher.raw(encode('MULTI') + encode('PING') + encode('EXEC'))
            assert [watcher.read(), watcher.read()] == [b'OK', b'QUEUED']
            result['watch_present'] = watcher.read()
            watcher.must('WATCH', 'flushfix2:absent')
            c.must('FLUSHALL')
            watcher.raw(encode('MULTI') + encode('PING') + encode('EXEC'))
            assert [watcher.read(), watcher.read()] == [b'OK', b'QUEUED']
            result['watch_absent'] = watcher.read()
        c.must('XGROUP', 'CREATE', 'flushfix2:stream', 'g', '$', 'MKSTREAM')
        with conn(b, args) as reader:
            reader.raw(encode('XREADGROUP', 'GROUP', 'g', 'c', 'BLOCK', 0,
                              'STREAMS', 'flushfix2:stream', '>'))
            s.wait(lambda: s.stats(c, 'clients').get('blocked_clients', 0) > 0,
                   'stream waiter never blocked', args.stall)
            c.must('FLUSHALL')
            result['xreadgroup'] = reader.read()
        c.must('SET', pair[0], 'old')
        before_pipeline = {} if oracle else s.stats(c)
        c.raw(encode('FLUSHALL') + encode('GET', pair[0]) + encode('SET', pair[0], 'new') +
              encode('GET', pair[0]))
        result['pipeline'] = [c.read() for _ in range(4)]
        after_pipeline = {} if oracle else s.stats(c)
        assert [c.must('GET', key) for key in pair] == [b'new', None]
        after_clean = {} if oracle else s.stats(c)
        lane = dict(pipeline={k:after_pipeline.get(k, 0)-before_pipeline.get(k, 0)
                             for k in ('read_local_hits', 'read_local_fallbacks',
                                       'read_local_fallback_inflight_write')},
                    clean_hits=after_clean.get('read_local_hits', 0)-after_pipeline.get('read_local_hits', 0))
        (directory / 'pipeline-lane.json').write_text(json.dumps(lane, indent=2)+'\n')
        if not oracle and mode == '1s':
            assert lane['pipeline']['read_local_hits'] + lane['pipeline']['read_local_fallbacks'] >= 2, lane
            assert lane['clean_hits'] > 0, ('read-local lane did not resume after FLUSH', lane)
        with conn(b, args) as tracker:
            tracker.must('HELLO', 3)
            tracker.must('CLIENT', 'TRACKING', 'ON', 'BCAST')
            tracker.raw(encode('FLUSHALL') + encode('PING'))
            result['tracking_order'] = [tracker.read() for _ in range(3)]
        result = normalized(result) if not isinstance(result, dict) else {k: normalized(v) for k, v in result.items()}
        (directory / 'siblings.json').write_text(json.dumps(result, indent=2) + '\n')
        if oracle:
            ORACLE[args.databases] = result
        else:
            assert args.databases in ORACLE, 'oracle must run before target'
            assert result == ORACLE[args.databases], (result, ORACLE[args.databases])
        return result


def swapdb(args, directory, mode, engine, atomic, oracle):
    other = 7 if args.databases == 16 else 0
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        pair, _ = s.keys_for(b.c, 'flushfix2:swap', oracle, 2)
        for db in (0, other):
            b.c.must('SELECT', db)
            b.c.must('MSET', pair[0], db, pair[1], db)
        counts = dict(swaps=0, observations=0, torn=0)
        def swap(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    c.must('SWAPDB', 0, other)
                    counts['swaps'] += 1
        def observe(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    values = c.must('MGET', *pair)
                    counts['observations'] += 1
                    counts['torn'] += values not in ([b'0', b'0'], [str(other).encode()]*2)
        errors = s.run_storm(args.seconds, [swap, observe], args.stall)
        assert not errors and counts['swaps'] and counts['observations'] and not counts['torn'], (counts, errors)
        return counts


def namespace_mutations(args, directory, mode, engine, atomic, oracle):
    """MOVE has one resident across DBs; COPY/RESTORE never expose a gap."""
    result = dict(moves=0, copies=0, restores=0, move_reads=0, copy_reads=0, restore_reads=0)
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        c = b.c
        c.must('MSET', 'move:key', 1, 'copy:key', 1, 'restore:key', 1)
        dumped = c.must('DUMP', 'restore:key')
        if args.databases > 1:
            c.must('COPY', 'copy:key', 'copy:key', 'DB', 7)
        def move(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    for source, destination in ((0, 7), (7, 0)):
                        c.must('SELECT', source)
                        assert c.must('MOVE', 'move:key', destination) == 1
                        result['moves'] += 1
        def move_read(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    c.raw(encode('MULTI') + encode('SELECT', 0) + encode('GET', 'move:key') +
                          encode('SELECT', 7) + encode('GET', 'move:key') + encode('EXEC'))
                    assert [c.read() for _ in range(5)] == [b'OK'] + [b'QUEUED']*4
                    reply = c.read()
                    assert reply in ([b'OK', b'1', b'OK', None], [b'OK', None, b'OK', b'1']), reply
                    result['move_reads'] += 1
        def copy(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    assert c.must('COPY', 'copy:key', 'copy:key', 'DB', 7, 'REPLACE') == 1
                    result['copies'] += 1
        def copy_read(stop):
            with conn(b, args, 7) as c:
                while not stop.is_set():
                    assert c.must('GET', 'copy:key') == b'1'
                    result['copy_reads'] += 1
        def restore(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    assert c.must('RESTORE', 'restore:key', 0, dumped, 'REPLACE') == b'OK'
                    result['restores'] += 1
        def restore_read(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    assert c.must('GET', 'restore:key') == b'1'
                    result['restore_reads'] += 1
        workers = [restore, restore_read]
        if args.databases > 1:
            workers += [move, move_read, copy, copy_read]
        errors = s.run_storm(args.seconds, workers, args.stall)
        result['errors'] = errors
        (directory/'siblings.json').write_text(json.dumps(result, indent=2)+'\n')
        assert not errors, result
        assert result['restores'] and result['restore_reads'], result
        if args.databases > 1:
            assert all(result[k] for k in ('moves', 'move_reads', 'copies', 'copy_reads')), result
        return result


def reload(args, directory, mode, engine, atomic, oracle):
    aof = args.case == 'debug-loadaof'
    extra = ('--appendonly', 'yes', '--appendfsync', 'always') if aof else ()
    with s.Boot(args, directory, mode, engine, atomic, oracle, extra=extra) as b:
        c = b.c
        pair, _ = s.keys_for(c, 'flushfix2:reload', oracle, 2)
        for begin in range(0, 12000, 500):
            c.raw(b''.join(encode('SET', f'flushfix2:bulk:{i}', 'v' * 64) for i in range(begin, begin+500)))
            assert all(c.read() == b'OK' for _ in range(500))
        # Put the observed keys at the end of the AOF: loading the intervening
        # residents exposes the clear-to-reinsert window to stamped reads.
        for key in pair:
            c.must('SET', key, 1)
        c.must('SAVE')
        counts = dict(loads=0, pair_reads=0, get_reads=0, torn=0, missing=0,
                      pair_missing=0, loading_replies=0, writes=0, script_torn=0,
                      load_errors=0, get_regressions=0)
        observer_ready = threading.Event()
        single_ready = threading.Event()
        writer_ready = threading.Event()
        def loading(value):
            if isinstance(value, RespError) and value.message.startswith(b'LOADING '):
                assert oracle, value
                counts['loading_replies'] += 1
                return True
            if isinstance(value, RespError):
                raise value
            return False
        def load(stop):
            with conn(b, args) as x:
                assert observer_ready.wait(args.stall), 'reload observer never armed'
                assert single_ready.wait(args.stall), 'single-key observer never armed'
                assert writer_ready.wait(args.stall), 'reload writer never armed'
                while not stop.is_set():
                    reply = x.cmd('DEBUG', 'LOADAOF' if aof else 'RELOAD')
                    if isinstance(reply, RespError):
                        counts['load_errors'] += 1
                        continue
                    assert reply == b'OK', reply
                    counts['loads'] += 1
        def observe(stop):
            with conn(b, args) as x:
                while not stop.is_set():
                    v = x.cmd('MGET', *pair)
                    if loading(v):
                        continue
                    counts['pair_reads'] += 1
                    observer_ready.set()
                    counts['torn'] += v[0] != v[1]
                    counts['pair_missing'] += any(value is None for value in v)
        def single(stop):
            with conn(b, args) as x:
                previous = 0
                while not stop.is_set():
                    v = x.cmd('GET', pair[0])
                    if loading(v):
                        continue
                    counts['get_reads'] += 1
                    single_ready.set()
                    counts['missing'] += v is None
                    assert v is None or int(v) > 0
                    if v is not None:
                        current = int(v)
                        counts['get_regressions'] += current < previous
                        previous = current
        def write(stop):
            with conn(b, args) as x:
                while not stop.is_set():
                    reply = x.cmd('EVAL', s.WRITE, 2, *pair)
                    if loading(reply):
                        continue
                    assert isinstance(reply, list) and len(reply) == 2, reply
                    counts['script_torn'] += reply[0] != reply[1]
                    counts['writes'] += 1
                    writer_ready.set()
        errors = s.run_storm(args.seconds, [load, observe, single, write], args.stall)
        result = dict(**counts, errors=errors)
        (directory / 'reload-witness.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not errors and counts['loads'] and counts['pair_reads'] and counts['get_reads'] and counts['writes'], result
        assert not any(counts[k] for k in ('torn', 'missing', 'pair_missing', 'script_torn', 'load_errors', 'get_regressions')), result
        return result


def storm(args, directory, mode, engine, atomic, oracle):
    aof = args.case == 'aof-restart'
    save = args.case in ('bgsave-straddle', 'live-bgsave')
    extra = ('--appendonly', 'yes', '--appendfsync', 'always') if aof else ()
    saved = []
    expected_aof = None
    sentinels = {}
    counts = dict(flushes=0, work=0, saves=0, flips=0, flip_refusals=0, cancelled_saves=0)
    with s.Boot(args, directory, mode, engine, atomic, oracle, extra=extra) as b:
        if aof:
            for db in range(args.databases):
                b.c.must('SELECT', db)
                by_shard = {}
                for i in range(4000):
                    key = f'flushfix2:aof:must-disappear:{db}:{i}'
                    sid = i if oracle else s.placement(b.c, key)[0]
                    if sid not in by_shard:
                        b.c.must('SET', key, 'before-flush')
                        by_shard[sid] = key
                    if len(by_shard) == 16:
                        break
                assert len(by_shard) == 16, 'AOF sentinel coverage missed a shard'
                sentinels[db] = list(by_shard.values())
            b.c.must('SELECT', 0)
        pair, _ = s.keys_for(b.c, 'flushfix2:storm', oracle, 2)
        def flush(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    if args.case == 'live-flip':
                        # Test FLUSH+FLIP without a retained MULTI session. The
                        # independent live-flip-cut row retains that stronger
                        # interaction and its PRE failure evidence.
                        c.raw(encode('MSET', pair[0], 1, pair[1], 1) +
                              encode('FLUSHALL', args.flush_mode))
                        assert [c.read(), c.read()] == [b'OK', b'OK']
                    else:
                        c.raw(encode('MULTI') + encode('SET', pair[0], 1) + encode('SET', pair[1], 1) +
                              encode('EXEC') + encode('FLUSHALL', args.flush_mode))
                        assert [c.read() for _ in range(5)] == [b'OK', b'QUEUED', b'QUEUED', [b'OK', b'OK'], b'OK']
                    counts['flushes'] += 1
        def worker(stop):
            with conn(b, args) as c:
                workpair, _ = s.keys_for(c, 'flushfix2:live', oracle, 2)
                while not stop.is_set():
                    if args.case == 'live-script':
                        c.must('EVAL', s.WRITE, 2, *workpair)
                    elif args.case == 'live-watch':
                        c.must('WATCH', *workpair)
                        c.raw(encode('MULTI') + encode('INCR', workpair[0]) + encode('INCR', workpair[1]) + encode('EXEC'))
                        assert [c.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
                        value = c.read()
                        assert value is None or len(value) == 2
                    else:
                        c.must('DEL', *workpair)
                        c.must('MSETNX', workpair[0], 1, workpair[1], 1)
                    counts['work'] += 1
        def saver(stop):
            with conn(b, args) as c:
                filename = c.must('CONFIG', 'GET', 'dbfilename')[1].decode()
                s.wait(lambda: counts['flushes'] > 0, 'flush storm never started', args.stall)
                while not stop.is_set():
                    source = directory / filename
                    def generation():
                        if not source.exists():
                            return None
                        stat = source.stat()
                        return stat.st_ino, stat.st_mtime_ns, stat.st_size
                    before = generation()
                    c.must('BGSAVE')
                    s.wait(lambda: s.persistence(c)['rdb_bgsave_in_progress'] == '0', 'BGSAVE stalled', args.stall)
                    assert s.persistence(c)['rdb_last_bgsave_status'] == 'ok'
                    after = generation()
                    if oracle and (after is None or after == before):
                        # Redis 7.4 flushAllData() explicitly kills an active
                        # RDB child. Record that outcome, never count it as an
                        # image checked. The target must produce real images.
                        counts['cancelled_saves'] += 1
                        continue
                    assert after is not None and after != before, 'BGSAVE did not publish a new image'
                    path = directory / f'captured-{len(saved)}.rdb'
                    shutil.copyfile(source, path)
                    saved.append(path)
                    counts['saves'] += 1
                    if len(saved) == 8:
                        stop.wait()
                        return
        def flipper(stop):
            with conn(b, args) as c:
                while not stop.is_set():
                    target = 4 if counts['flips'] % 2 == 0 else 6
                    reply = c.cmd('FLIP', target, 8-target)
                    if isinstance(reply, RespError):
                        assert reply.message.startswith(b'ERR FLIP cannot quiesce a connection:'), reply
                        counts['flip_refusals'] += 1
                        continue
                    assert reply == b'OK', reply
                    counts['flips'] += 1
        workers = [flush] + ([] if args.case == 'live-flip' else [worker]) + ([saver] if save else [])
        if args.case in ('live-flip', 'live-flip-cut') and not oracle:
            assert mode == '2s'
            workers.append(flipper)
        errors = s.run_storm(args.seconds, workers, args.stall)
        assert not errors and counts['flushes'], (counts, errors)
        assert args.case == 'live-flip' or counts['work'], counts
        assert not save or counts['saves'] or (oracle and counts['cancelled_saves']), counts
        assert args.case not in ('live-flip', 'live-flip-cut') or oracle or counts['flips'], counts
        b.c.raw(encode('MULTI') + encode('SET', pair[0], 42) + encode('SET', pair[1], 42) + encode('EXEC'))
        assert [b.c.read() for _ in range(4)] == [b'OK', b'QUEUED', b'QUEUED', [b'OK', b'OK']]
        if aof:
            expected_aof = {}
            for db, keys in sentinels.items():
                b.c.must('SELECT', db)
                assert b.c.must('MGET', *keys) == [None]*len(keys)
                keys = sorted(b.c.must('KEYS', '*'))
                expected_aof[db] = (keys, b.c.must('MGET', *keys) if keys else [], b.c.must('DBSIZE'))
    for image in saved:
        recover = directory / (image.stem + '-reload')
        recover.mkdir()
        shutil.copyfile(image, recover / ('dump.rdb' if oracle else 'dump.tomo'))
        with s.Boot(args, recover, mode, engine, atomic, oracle) as b:
            v = b.c.must('MGET', *pair)
            assert v in ([None, None], [b'1', b'1']), (image, v)
        shutil.rmtree(recover)
    if aof:
        with s.Boot(args, directory, mode, engine, atomic, oracle, extra=extra, name='restart') as b:
            assert b.c.must('MGET', *pair) == [b'42', b'42']
            for db, expected in expected_aof.items():
                b.c.must('SELECT', db)
                keys = sorted(b.c.must('KEYS', '*'))
                assert (keys, b.c.must('MGET', *keys) if keys else [], b.c.must('DBSIZE')) == expected
    return dict(**counts, snapshots_checked=len(saved),
                aof_sentinels=sum(map(len, sentinels.values())), aof_namespaces=len(sentinels))


f.CASES = {'semantics': semantics, 'swapdb': swapdb, 'namespace-mutations': namespace_mutations,
           'debug-reload': reload, 'debug-loadaof': reload,
           **{name: storm for name in ('live-cut', 'live-script', 'live-watch', 'live-bgsave',
                                      'live-flip', 'live-flip-cut', 'bgsave-straddle', 'aof-restart')}}
if __name__ == '__main__':
    raise SystemExit(f.main())
