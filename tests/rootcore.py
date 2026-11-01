#!/usr/bin/env python3
"""Directed rootcore witnesses, invoked by the gate's ordinary job interface."""
import argparse
import copy
import hashlib
from pathlib import Path
import resource
import signal
import select
import time

from _lib import Conn, RespError, info
from persistfix2 import boot, emit, wait, rewrite_done


def eval_oom(a):
    for verb in ('EVAL', 'EVALSHA'):
        for flags, body, expected in (
                ('allow-oom', "return redis.call('SET',KEYS[1],'after')", b'OK'),
                ('no-writes', "return redis.call('GET',KEYS[1])", b'before')):
            with boot(a, f'{verb}-{flags}', ['--databases', str(a.databases),
                                           '--atomic', str(a.atomic)] if not a.oracle else ()) as (_, c, _):
                assert c.must('SET', 'rootcore:key', 'before') == b'OK'
                source = '#!lua flags=' + flags + '\n' + body
                sha = c.must('SCRIPT', 'LOAD', source)
                assert c.must('CONFIG', 'SET', 'maxmemory-policy', 'noeviction') == b'OK'
                assert c.must('CONFIG', 'SET', 'maxmemory', 1) == b'OK'
                denied = c.cmd('SET', 'rootcore:key', 'denied')
                assert isinstance(denied, RespError) and b'OOM' in denied.message, denied
                assert c.must('MULTI') == b'OK'
                assert c.must(verb, sha if verb == 'EVALSHA' else source, 1,
                              'rootcore:key') == b'QUEUED'
                emit('risky moment', case='flagged EXEC child over maxmemory', hits=1,
                     verb=verb, flags=flags)
                result = c.cmd('EXEC')
                assert result == [expected], result
                assert c.must('CONFIG', 'SET', 'maxmemory', 0) == b'OK'
                assert c.must('GET', 'rootcore:key') == (b'after' if flags == 'allow-oom' else b'before')


def functions(a):
    opts = ['--appendonly', 'yes', '--appendfsync', a.fsync]
    source = "#!lua name=rootcore\nredis.register_function('rootcore',function() return 17 end)"
    with boot(a, 'write', opts) as (_, c, data):
        assert c.must('SET', 'rootcore:key', 'before') == b'OK'
        c.must('BGREWRITEAOF')
        wait(lambda: rewrite_done(c), 'rewrite completed')
        assert c.must('FUNCTION', 'LOAD', source) == b'rootcore'
        dump = c.must('FUNCTION', 'DUMP')
        assert c.must('SET', 'rootcore:key', 'after') == b'OK'
        emit('risky moment', case='function mutation after AOF base', hits=1,
             fsync=a.fsync, functions=c.must('FUNCTION', 'LIST', 'WITHCODE'))
    with boot(a, 'read', opts, existing_data=data) as (_, c, _):
        assert c.must('GET', 'rootcore:key') == b'after'
        assert c.must('FCALL', 'rootcore', 0) == 17
        assert c.must('FUNCTION', 'DELETE', 'rootcore') == b'OK'
        emit('risky moment', case='FUNCTION DELETE in increment', hits=1)
    with boot(a, 'deleted', opts, existing_data=data) as (_, c, _):
        assert c.must('FUNCTION', 'LIST') == []
        assert c.must('FUNCTION', 'RESTORE', dump, 'FLUSH') == b'OK'
        emit('risky moment', case='FUNCTION RESTORE in increment', hits=1)
    with boot(a, 'restored', opts, existing_data=data) as (_, c, _):
        assert c.must('FCALL', 'rootcore', 0) == 17
        assert c.must('FUNCTION', 'FLUSH', 'ASYNC') == b'OK'
        emit('risky moment', case='FUNCTION FLUSH in increment', hits=1)
    with boot(a, 'flushed', opts, existing_data=data) as (_, c, _):
        assert c.must('FUNCTION', 'LIST') == []
        # The control frame must also carry records larger than a shard chunk.
        assert c.must('FUNCTION', 'LOAD', source + '\n--' + 'x' * 70000) == b'rootcore'
        emit('risky moment', case='large FUNCTION journal record', hits=1)
    with boot(a, 'large', opts, existing_data=data) as (_, c, _):
        assert c.must('FCALL', 'rootcore', 0) == 17


def segments(a):
    opts = ['--appendonly', 'yes', '--appendfsync', 'always']
    with boot(a, 'seed', opts) as (_, c, data):
        assert c.must('SET', 'rootcore:key', 'before') == b'OK'
        c.must('BGREWRITEAOF')
        wait(lambda: rewrite_done(c), 'rewrite completed')
    folder = data / 'appendonlydir'
    orphan = folder / 'appendonly.aof.999.incr.tomo'
    orphan.write_bytes(b'rootcore unreferenced evidence\x00\xff')
    digest = hashlib.sha256(orphan.read_bytes()).hexdigest()
    emit('risky moment', case='unreferenced segment at boot', hits=1, sha256=digest)
    with boot(a, 'restart', opts, existing_data=data) as (_, c, _):
        assert c.must('GET', 'rootcore:key') == b'before'
        preserved = [p for p in folder.rglob('*') if p.is_file() and
                     hashlib.sha256(p.read_bytes()).hexdigest() == digest]
        assert preserved, 'boot deleted an unreferenced segment'
    (folder / 'appendonly.aof.manifest').unlink()
    evidence = {p: p.read_bytes() for p in folder.glob('*.tomo')}
    emit('risky moment', case='missing manifest', hits=1, files=len(evidence))
    with boot(a, 'no-manifest', opts, existing_data=data):
        for p, content in evidence.items():
            assert any(q.read_bytes() == content for q in folder.rglob('*') if q.is_file()), p


def waitaof(a):
    with boot(a, 'waitaof', ['--appendonly', 'yes', '--appendfsync', a.fsync]) as (_, c, _):
        emit('risky moment', case='AOF-enabled local durability query', hits=1)
        result = c.must('WAITAOF', 0, 0, 1)
        assert result == [1, 0], result
        assert c.must('SET', 'rootcore:key', 'value') == b'OK'
        emit('risky moment', case='WAITAOF after AOF write', hits=1, fsync=a.fsync)
        assert c.must('WAITAOF', 1, 0, 3000) == [1, 0]
        assert c.must('WAITAOF', 0, 0, 1) == [1, 0]
        observer = Conn('127.0.0.1', a.port, timeout=5)
        try:
            assert c.must('CONFIG', 'SET', 'appendfsync', 'no') == b'OK'
            assert c.must('SET', 'rootcore:unsynced', 'pending') == b'OK'
            assert c.must('WAITAOF', 0, 0, 1) == [0, 0]
            assert observer.must('WAITAOF', 0, 0, 1) == [1, 0]
            assert c.must('WAITAOF', 1, 0, 5) == [0, 0]
            c.send('WAITAOF', 1, 0, 0)
            wait(lambda: int(info(observer, 'clients')['blocked_clients']) == 1,
                 'local fsync waiter parked')
            emit('risky moment', case='unsynced connection parked; untouched connection acknowledged', hits=1)
            assert observer.must('CONFIG', 'SET', 'appendfsync', 'always') == b'OK'
            assert c.read() == [1, 0]
            assert c.must('MULTI') == b'OK'
            assert c.must('WAITAOF', 1, 1, 0) == b'QUEUED'
            assert c.must('EXEC') == [[1, 0]]
        finally:
            observer.close()


def notify(a):
    opts = ['--appendonly', 'yes', '--appendfsync', 'always',
            '--notify-keyspace-events', 'AKE', '--databases', str(a.databases)]
    if not a.oracle:
        opts += ['--atomic', str(a.atomic)]
    with boot(a, 'write', opts) as (_, c, data):
        sub = Conn('127.0.0.1', a.port, timeout=3)
        assert sub.must('PSUBSCRIBE', '__keyevent@0__:*')[0] == b'psubscribe'
        assert c.must('RPUSH', 'rootcore:{same}:source', 3, 1, 2) == 3
        assert c.must('SORT', 'rootcore:{same}:source', 'STORE', 'rootcore:{same}:dest') == 3
        c.must('XADD', 'rootcore:stream', '1-0', 'field', 'value')
        c.must('XGROUP', 'CREATE', 'rootcore:stream', 'group', '0')
        result = c.must('XREADGROUP', 'GROUP', 'group', 'consumer', 'STREAMS', 'rootcore:stream', '>')
        assert result and result[0][1][0][0] == b'1-0'
        pending = c.must('XPENDING', 'rootcore:stream', 'group')
        seen = set()
        while not {b'__keyevent@0__:sortstore', b'__keyevent@0__:xgroup-createconsumer'} <= seen:
            event = sub.read()
            assert event[0] == b'pmessage', event
            seen.add(event[2])
        sub.close()
        emit('notification attachment witnessed', events=sorted(seen), hits=2)
        emit('risky moment', case='notifications with local SORT STORE and XREADGROUP',
             hits=2, pending=pending)
    with boot(a, 'read', opts, existing_data=data) as (_, c, _):
        recovered = c.must('LRANGE', 'rootcore:{same}:dest', 0, -1)
        recovered_pending = c.must('XPENDING', 'rootcore:stream', 'group')
        emit('recovered post-images', sort=recovered, pending=recovered_pending)
        assert (recovered, recovered_pending) == ([b'1', b'2', b'3'], pending), (recovered, recovered_pending)


def misconf(a):
    opts = ['--appendonly', 'yes', '--appendfsync', a.fsync]
    # A reversible per-process write limit opens a real ENOSPC-like failure;
    # the hard limit remains unchanged so prlimit can restore it afterwards.
    with boot(a, 'failure', opts, fsize=resource.RLIM_INFINITY) as (p, c, data):
        assert c.must('SET', 'rootcore:before', 'before') == b'OK'
        wait(lambda: int(info(c, 'persistence')['aof_current_size']) > 0,
             'initial AOF write')
        old = resource.prlimit(p.pid, resource.RLIMIT_FSIZE)
        # SIGXFSZ is ignored by TomoKV's AOF setup and Redis.
        resource.prlimit(p.pid, resource.RLIMIT_FSIZE, (1, old[1]))
        c.cmd('SET', 'rootcore:failed', 'x' * 4096)
        wait(lambda: info(c, 'persistence')['aof_last_write_status'] == 'err', 'write failure')
        denied = c.cmd('SET', 'rootcore:denied', 'denied')
        assert isinstance(denied, RespError) and b'MISCONF' in denied.message, denied
        emit('risky moment', case='failed AOF write and MISCONF observed', hits=1)
        resource.prlimit(p.pid, resource.RLIMIT_FSIZE, old)
        wait(lambda: info(c, 'persistence')['aof_last_write_status'] == 'ok',
             'AOF retry cleared MISCONF', 5)
        assert c.must('SET', 'rootcore:after', 'after') == b'OK'
    with boot(a, 'read', opts, existing_data=data) as (_, c, _):
        assert c.must('GET', 'rootcore:before') == b'before'
        assert c.must('GET', 'rootcore:failed') == b'x' * 4096
        assert c.must('GET', 'rootcore:after') == b'after'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', required=True, choices=('eval', 'functions', 'segments', 'waitaof', 'notify', 'misconf'))
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--oracle-binary', type=Path, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    args.output.mkdir(parents=True, exist_ok=True)
    failures = []
    # The oracle has no native segment format. All other rows run it first.
    endpoints = [(False, mode, engine) for mode in ('1s', '2s') for engine in ('uring', 'epoll')]
    if args.case != 'segments':
        endpoints.insert(0, (True, 'oracle', 'normal'))
    for oracle, mode, engine in endpoints:
        for fsync in (('always', 'everysec') if args.case in ('functions', 'waitaof') else
                      ('everysec', 'no') if args.case == 'misconf' else ('always',)):
            for databases in ((1, 16) if not oracle and args.case in ('eval', 'notify') else (1,)):
                for atomic in ((0, 1) if not oracle and args.case in ('eval', 'notify') else (0,)):
                    a = copy.copy(args)
                    a.oracle, a.mode, a.engine, a.fsync = oracle, mode, engine, fsync
                    a.databases, a.atomic = databases, atomic
                    if oracle:
                        a.binary = args.oracle_binary
                    label = f'{mode}-{engine}-{fsync}-db{databases}-a{atomic}'
                    a.output = args.output / label
                    a.output.mkdir()
                    emit('geometry', case=args.case, leg=label, cores=args.cores,
                         shards=16, ratio=args.ratio)
                    try:
                        globals()[args.case if args.case != 'eval' else 'eval_oom'](a)
                        emit('pass', leg=label)
                    except Exception as error:
                        emit('FAIL', leg=label, error=repr(error))
                        failures.append(label + ': ' + repr(error))
    assert not failures, '\n'.join(failures)


if __name__ == '__main__':
    main()
