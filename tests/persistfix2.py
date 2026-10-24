#!/usr/bin/env python3
"""Persistence command/recovery assertions against the Redis 7.4 oracle.

Every invocation owns fresh data, its child PID and its port. A required active
state must be observed; bounded retries use fresh state and never skip an arm.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time

from _lib import Conn, RespError, info, wait_ready
from persistfix import check_port_owner, guard_port


def serial(value):
    if isinstance(value, bytes):
        return value.decode(errors='backslashreplace')
    if isinstance(value, RespError):
        return {'error': str(value)}
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def emit(event, **fields):
    print(json.dumps(dict(event=event, **serial(fields)), sort_keys=True), flush=True)


def wait(predicate, description, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.005)
    raise AssertionError('required state not observed: ' + description)


@contextlib.contextmanager
def boot(args, name, extra=(), fsize=None):
    directory = args.output / name
    directory.mkdir(parents=True, exist_ok=False)
    data = directory / 'data'
    data.mkdir()
    guard_port(args.port)
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(data),
            '--dbfilename', 'dump.rdb', '--save', '', '--appendonly', 'no',
            '--protected-mode', 'no', '--enable-debug-command', 'yes',
            '--auto-aof-rewrite-percentage', '0', '--databases', '1']
    if not args.oracle:
        argv += ['--thread-mode', args.mode, '--net-io', args.engine, '--shards', '16',
                 '--read-local', '0', '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
        if args.mode == '2s':
            argv += ['--ratio', args.ratio]
    argv += list(extra)
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')

    def limits():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if fsize is not None:
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)

    with (directory / 'server.log').open('wb') as logfile:
        process = subprocess.Popen(argv, stdout=logfile, stderr=logfile, preexec_fn=limits)
        conn = None
        emit('boot', argv=argv, pid=process.pid)
        try:
            conn = wait_ready('127.0.0.1', args.port, timeout=15, process=process)
            check_port_owner(args.port, process.pid)
            yield process, conn, data
        finally:
            if conn:
                conn.close()
            # Remove only this invocation's DEBUG hold, allowing owned teardown.
            (data / 'appendonlydir/debug-aof-rewrite-stage').unlink(missing_ok=True)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    emit('unclean stop', reason='owned test cleanup after refusal', code=process.returncode)
            wait(lambda: not subprocess.check_output(
                ['ss', '-ltnH', f'sport = :{args.port}']).strip(), 'owned listener closed', 5)
            emit('exit', code=process.returncode)


def command(conn, *words):
    conn.send(*words)
    result = conn.read()
    emit('reply', command=words, reply=result)
    return result


def persistence(conn):
    return info(conn, 'persistence')


def rewrite_done(conn):
    values = persistence(conn)
    return values if values['aof_rewrite_in_progress'] == '0' and \
        values['aof_rewrite_scheduled'] == '0' else None


def observer(args, conn):
    if args.oracle:
        return conn
    roles = conn.must('DEBUG', 'LBSIGNALS').decode().splitlines()
    writer = max(int(row.split()[1]) for row in roles
                 if row.startswith('thread ') and row.split()[2] in ('io', 'fused'))
    for _ in range(128):
        other = Conn('127.0.0.1', args.port, timeout=15)
        if other.must('DEBUG', 'IO-THREAD') != writer:
            return other
        other.close()
    raise AssertionError('required rewrite observer was not assigned')


def lastsave(args):
    options = ['--appendonly', 'yes', '--appendfsync', 'always']
    if args.oracle:
        options += ['--rdb-key-save-delay', '100']
    with boot(args, 'lastsave', options) as (_, conn, data):
        for start in range(0, 2000, 200):
            assert conn.must('MSET', *[word for i in range(start, start + 200)
                                     for word in (f'persistfix2:{i}', 'value')]) == b'OK'
        assert command(conn, 'SAVE') == b'OK'
        assert conn.must('SET', 'acknowledged-write', 'after-save') == b'OK'
        before = persistence(conn)
        saved = command(conn, 'LASTSAVE')
        wait(lambda: int(time.time()) > saved, 'next LASTSAVE second', 3)
        watch = observer(args, conn)
        try:
            if not args.oracle:
                assert command(watch, 'DEBUG', 'AOF-REWRITE-PAUSE', 'before-manifest') == b'OK'
            assert command(watch, 'BGREWRITEAOF') == b'Background append only file rewriting started'
            if not args.oracle:
                wait(lambda: (data / 'appendonlydir/debug-aof-rewrite-stage').exists(),
                     'rewrite finalization durability window')
            active = wait(lambda: (v if (v := persistence(watch))['aof_rewrite_in_progress'] == '1'
                                   else None), 'active rewrite')
            (data / 'appendonlydir/debug-aof-rewrite-stage').unlink(missing_ok=True)
            after = wait(lambda: rewrite_done(watch), 'completed rewrite')
            after_saved = command(watch, 'LASTSAVE')
            emit('rewrite persistence', before=before, active=active, after=after,
                 lastsave_before=saved, lastsave_after=after_saved)
            failures = []
            if after_saved != saved:
                failures.append('LASTSAVE advanced without an RDB save')
            for field in ('rdb_last_save_time', 'rdb_changes_since_last_save',
                          'rdb_last_bgsave_status', 'rdb_saves', 'rdb_bgsave_in_progress'):
                if not (before[field] == active[field] == after[field]):
                    failures.append(f'{field}: {before[field]} -> {active[field]} -> {after[field]}')
            if int(active['aof_rewrites']) != int(before['aof_rewrites']) + 1:
                failures.append('aof_rewrites must count the started rewrite')
            assert int(after['aof_rewrites']) == int(before['aof_rewrites']) + 1
            assert after['aof_last_bgrewrite_status'] == 'ok'
            assert after['aof_rewrites_consecutive_failures'] == '0'
            assert not failures, '; '.join(failures)
        finally:
            if watch is not conn:
                watch.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('lastsave',), required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--oracle', action='store_true')
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--engine', choices=('epoll', 'uring'), required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    globals()[args.case](args)
    emit('PASS', case=args.case, oracle=args.oracle, mode=args.mode, engine=args.engine)


if __name__ == '__main__':
    main()
