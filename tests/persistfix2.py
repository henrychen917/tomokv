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
import threading
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
def boot(args, name, extra=(), fsize=None, existing_data=None):
    directory = args.output / name
    directory.mkdir(parents=True, exist_ok=False)
    data = existing_data or directory / 'data'
    if existing_data is None:
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
            with contextlib.suppress(NotADirectoryError):
                (data / 'appendonlydir/debug-aof-rewrite-stage').unlink(missing_ok=True)
            if process.poll() is None:
                try:
                    cleanup = Conn('127.0.0.1', args.port, timeout=.5)
                    cleanup.send('SHUTDOWN', 'NOSAVE')
                    cleanup.close()
                except OSError:
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


def shutdown(args):
    failures = []

    def check(name, run):
        try:
            run()
        except Exception as error:
            emit('assertion', name=name, error=str(error))
            failures.append(f'{name}: {error}')

    def grammar():
        with boot(args, 'grammar') as (_, conn, _):
            for words in [('ABORT',), ('ABORT', 'ABORT'), ('ABORT', 'bogus'),
                          ('SAVE', 'NOSAVE'), ('ABORT', 'SAVE'), ('NOW', 'ABORT'),
                          ('FORCE', 'ABORT'), ('ABORT', 'NOSAVE'),
                          ('ABORT', 'ABORT', 'ABORT', 'ABORT', 'ABORT')]:
                expected = 'ERR No shutdown in progress.' if set(words) == {'ABORT'} else 'ERR syntax error'
                reply = command(conn, 'SHUTDOWN', *words)
                if reply != RespError(expected):
                    failures.append(f'{words}: {reply!r} != {expected}')
            assert conn.must('PING') == b'PONG'
            assert conn.must('MULTI') == b'OK'
            assert command(conn, 'SHUTDOWN', 'NOSAVE') == RespError(
                'ERR Command not allowed inside a transaction')
            assert command(conn, 'EXEC') == RespError(
                'EXECABORT Transaction discarded because of previous errors.')
    check('grammar', grammar)

    def stop_case(name, words, configured, failed, signal_name=None, setting=None):
        extra = ['--save', '3600 1' if configured else '']
        with boot(args, name, extra) as (process, conn, data):
            assert conn.must('SET', 'acknowledged-write', 'value') == b'OK'
            if failed:
                (data / 'dump.rdb').mkdir()
            if setting is not None:
                key = 'shutdown-on-' + signal_name
                assert command(conn, 'CONFIG', 'SET', key, setting) == b'OK'
                wanted = ' '.join(word for word in ('save', 'nosave', 'now', 'force')
                                  if word in setting.lower().split()) or 'default'
                assert command(conn, 'CONFIG', 'GET', key) == [key.encode(), wanted.encode()]
            upper = set(words)
            saving = 'SAVE' in upper or (configured and 'NOSAVE' not in upper)
            refuse = saving and failed and 'FORCE' not in upper
            if signal_name:
                process.send_signal(signal.SIGTERM if signal_name == 'sigterm' else signal.SIGINT)
                if refuse:
                    logfile = data.parent / 'server.log'
                    wait(lambda: ('can\'t exit' in logfile.read_text(errors='replace') or
                                  'Errors trying to SHUTDOWN' in logfile.read_text(errors='replace')),
                         'signal save refusal')
                    assert process.poll() is None and conn.must('PING') == b'PONG'
                else:
                    assert process.wait(timeout=15) == 0
            else:
                conn.send('SHUTDOWN', *words)
                try:
                    reply = conn.read()
                except (EOFError, ConnectionResetError):
                    reply = 'closed'
                emit('shutdown reply', words=words, configured=configured, failed=failed, reply=reply)
                if refuse:
                    assert reply == RespError('ERR Errors trying to SHUTDOWN. Check logs.'), repr(reply)
                    assert process.poll() is None and conn.must('PING') == b'PONG'
                else:
                    assert reply == 'closed', repr(reply)
                    assert process.wait(timeout=15) == 0
            if not refuse and not failed:
                assert (data / 'dump.rdb').is_file() == saving

    combinations = [(), ('NOW',), ('FORCE',), ('NOW', 'FORCE'), ('SAVE',), ('NOSAVE',),
                    ('SAVE', 'NOW'), ('SAVE', 'FORCE'), ('NOSAVE', 'NOW'), ('NOSAVE', 'FORCE'),
                    ('SAVE', 'NOW', 'FORCE'), ('NOSAVE', 'NOW', 'FORCE'),
                    ('NOSAVE', 'NOW', 'FORCE', 'NOW', 'NOSAVE')]
    for index, words in enumerate(combinations):
        for failed in (False, True):
            name = f'command-{index}-{int(failed)}'
            check(name, lambda: stop_case(name, words, True, failed))
    for signal_name in ('sigterm', 'sigint'):
        for setting in ('default', 'save', 'nosave', 'save now', 'save force', 'nosave now force'):
            for configured in (False, True):
                name = f'{signal_name}-{setting.replace(" ", "-")}-{int(configured)}'
                words = tuple(setting.upper().split())
                check(name, lambda: stop_case(name, words, configured, True, signal_name, setting))

    def config_grammar():
        with boot(args, 'config') as (_, conn, _):
            for key in ('shutdown-on-sigterm', 'shutdown-on-sigint'):
                for value in ('SAVE save FORCE', 'default now nosave', 'force now save default'):
                    assert command(conn, 'CONFIG', 'SET', key, value) == b'OK'
                for value in ('save nosave', 'bogus', '', 'abort'):
                    suffix = "shutdown options SAVE and NOSAVE can't be used simultaneously" \
                        if value == 'save nosave' else \
                        'argument(s) must be one of the following: default, save, nosave, now, force'
                    expected = RespError(f"ERR CONFIG SET failed (possibly related to argument '{key}') - {suffix}")
                    assert command(conn, 'CONFIG', 'SET', key, value) == expected
                assert command(conn, 'CONFIG', 'SET', key, 'nosave') == b'OK'
    check('config grammar', config_grammar)
    for signal_name in ('sigterm', 'sigint'):
        def boot_policy():
            with boot(args, 'boot-' + signal_name,
                      ['--shutdown-on-' + signal_name, 'default', 'save', 'now', 'force']) as (process, conn, data):
                (data / 'dump.rdb').mkdir()
                assert command(conn, 'CONFIG', 'GET', 'shutdown-on-' + signal_name) == [
                    ('shutdown-on-' + signal_name).encode(), b'save now force']
                process.send_signal(signal.SIGTERM if signal_name == 'sigterm' else signal.SIGINT)
                assert process.wait(timeout=15) == 0
        check('boot policy ' + signal_name, boot_policy)
    def active_save():
        for attempt in range(3):
            extra = ['--rdb-key-save-delay', '100'] if args.oracle else []
            with boot(args, f'active-save-{attempt}', extra) as (process, conn, data):
                count = 4000 if args.oracle else 20000 * (attempt + 1)
                for start in range(0, count, 200):
                    assert conn.must('MSET', *[word for i in range(start, start + 200)
                                             for word in (f'persistfix2:{i}', 'v' * 1024)]) == b'OK'
                assert command(conn, 'BGSAVE') == b'Background saving started'
                if persistence(conn)['rdb_bgsave_in_progress'] != '1':
                    emit('fresh state retry', reason='BGSAVE completed before shutdown admission')
                    continue
                emit('active save observed', attempt=attempt)
                conn.send('SHUTDOWN', 'SAVE')
                try:
                    reply = conn.read()
                except (EOFError, ConnectionResetError):
                    reply = 'closed'
                emit('active save shutdown reply', reply=reply)
                assert reply == 'closed', repr(reply)
                assert process.wait(timeout=15) == 0
                assert (data / 'dump.rdb').is_file()
                return
        raise AssertionError('active BGSAVE shutdown state never observed')
    check('active BGSAVE shutdown', active_save)
    assert not failures, '\n'.join(failures)


def commands(args):
    failures = []
    def check(name, run):
        try:
            run()
        except Exception as error:
            emit('assertion', name=name, error=str(error))
            failures.append(f'{name}: {error}')

    def grammar():
        with boot(args, 'bgsave-grammar') as (_, conn, _):
            for words in [('bogus',), ('SCHEDULE', 'bogus'), ('SCHEDULE', 'SCHEDULE')]:
                reply = command(conn, 'BGSAVE', *words)
                if reply != RespError('ERR syntax error'):
                    failures.append(f'BGSAVE {words}: {reply!r}')
            wait(lambda: persistence(conn)['rdb_bgsave_in_progress'] == '0', 'idle RDB')
            assert command(conn, 'BGSAVE', 'ScHeDuLe') == b'Background saving started'
            wait(lambda: persistence(conn)['rdb_bgsave_in_progress'] == '0', 'completed RDB')
    check('BGSAVE grammar', grammar)

    def disabled():
        with boot(args, 'aof-disabled') as (_, conn, data):
            assert not (data / 'appendonlydir').exists()
            assert conn.must('SET', 'acknowledged-write', 'cut') == b'OK'
            before = persistence(conn)
            assert command(conn, 'BGREWRITEAOF') == b'Background append only file rewriting started'
            wait(lambda: rewrite_done(conn), 'disabled AOF rewrite complete')
            assert (data / 'appendonlydir').is_dir()
            assert list((data / 'appendonlydir').glob('*.manifest'))
            after = persistence(conn)
            assert after['aof_enabled'] == '0'
            assert after['rdb_last_save_time'] == before['rdb_last_save_time']
            assert after['aof_last_bgrewrite_status'] == 'ok'
            assert int(after['aof_rewrites']) == int(before['aof_rewrites']) + 1
            assert command(conn, 'BGREWRITEAOF') == b'Background append only file rewriting started'
            wait(lambda: rewrite_done(conn), 'second disabled AOF rewrite complete')
            assert conn.must('SET', 'acknowledged-write', 'later') == b'OK'
            emit('disabled AOF rewrite', before=before, after=persistence(conn),
                 files=sorted(p.name for p in (data / 'appendonlydir').iterdir()))
        with boot(args, 'disabled-rewrite-recovery', ['--appendonly', 'yes'], existing_data=data) as (_, conn, _):
            assert command(conn, 'GET', 'acknowledged-write') == b'cut'
            emit('recovery', result='explicit rewrite cut restored; later AOF-disabled write absent')
    check('disabled AOF rewrite', disabled)

    def directory_error():
        with boot(args, 'aof-directory-error') as (_, conn, data):
            (data / 'appendonlydir').write_text('ordinary file')
            assert command(conn, 'BGREWRITEAOF') == RespError(
                "ERR Can't execute an AOF background rewriting. Please check the server logs for more information.")
            assert persistence(conn)['aof_last_bgrewrite_status'] == 'err'
            assert conn.must('PING') == b'PONG'
    check('AOF directory error', directory_error)

    def save_error():
        with boot(args, 'save-error') as (_, conn, data):
            (data / 'dump.rdb').mkdir()
            assert command(conn, 'SAVE') == RespError('ERR')
            emit('SAVE error persistence', info=persistence(conn))
    check('SAVE error reply', save_error)

    def scheduled(enabled):
        for attempt in range(3):
            extra = ['--appendonly', 'yes' if enabled else 'no', '--appendfsync', 'no']
            if args.oracle:
                extra += ['--rdb-key-save-delay', '100']
            with boot(args, f'scheduled-{int(enabled)}-{attempt}', extra) as (_, conn, data):
                count = 4000 if args.oracle else 20000 * (attempt + 1)
                for start in range(0, count, 200):
                    assert conn.must('MSET', *[word for i in range(start, start + 200)
                                             for word in (f'persistfix2:{i}', 'v' * 1024)]) == b'OK'
                before = persistence(conn)
                assert command(conn, 'BGSAVE') == b'Background saving started'
                if persistence(conn)['rdb_bgsave_in_progress'] != '1':
                    emit('fresh state retry', reason='BGSAVE completed before rewrite scheduling')
                    continue
                assert command(conn, 'BGREWRITEAOF') == b'Background append only file rewriting scheduled'
                current = persistence(conn)
                emit('scheduled rewrite', info=current)
                assert current['aof_rewrite_scheduled'] == '1'
                assert current['aof_rewrite_in_progress'] == '0'
                assert command(conn, 'BGREWRITEAOF') == b'Background append only file rewriting scheduled'
                assert command(conn, 'BGSAVE') == RespError('ERR Background save already in progress')
                assert command(conn, 'SAVE') == RespError('ERR Background save already in progress')
                after = wait(lambda: rewrite_done(conn), 'scheduled rewrite complete')
                assert int(after['aof_rewrites']) == int(before['aof_rewrites']) + 1
                assert after['aof_last_bgrewrite_status'] == 'ok'
                assert after['rdb_last_bgsave_status'] == 'ok'
                return
        raise AssertionError('BGSAVE scheduling state never observed')
    check('rewrite during BGSAVE enabled', lambda: scheduled(True))
    check('rewrite during BGSAVE disabled', lambda: scheduled(False))

    def save_during_rewrite(blocking=False):
        extra = ['--appendonly', 'yes', '--appendfsync', 'no']
        if args.oracle:
            extra += ['--rdb-key-save-delay', '1000']
        with boot(args, 'save-during-rewrite-' + str(int(blocking)), extra) as (_, conn, data):
            for start in range(0, 2000, 200):
                assert conn.must('MSET', *[word for i in range(start, start + 200)
                                         for word in (f'persistfix2:{i}', 'v')]) == b'OK'
            watch = observer(args, conn)
            try:
                if not args.oracle:
                    assert command(watch, 'DEBUG', 'AOF-REWRITE-PAUSE', 'before-manifest') == b'OK'
                before = persistence(watch)
                assert command(watch, 'BGREWRITEAOF') == b'Background append only file rewriting started'
                if not args.oracle:
                    wait(lambda: (data / 'appendonlydir/debug-aof-rewrite-stage').exists(),
                         'rewrite durability window')
                assert persistence(watch)['aof_rewrite_in_progress'] == '1'
                if blocking:
                    release = threading.Timer(.05, lambda: (data / 'appendonlydir/debug-aof-rewrite-stage').unlink(missing_ok=True))
                    release.start()
                    try:
                        assert command(watch, 'SAVE') == b'OK'
                    finally:
                        release.join()
                    assert (data / 'dump.rdb').is_file()
                    return
                assert command(watch, 'BGREWRITEAOF') == RespError(
                    'ERR Background append only file rewriting already in progress')
                assert command(watch, 'BGSAVE') == RespError(
                    "ERR Another child process is active (AOF?): can't BGSAVE right now. Use BGSAVE SCHEDULE in order to schedule a BGSAVE whenever possible.")
                assert command(watch, 'BGSAVE', 'SCHEDULE') == b'Background saving scheduled'
                assert command(watch, 'BGSAVE', 'SCHEDULE') == b'Background saving scheduled'
                (data / 'appendonlydir/debug-aof-rewrite-stage').unlink(missing_ok=True)
                after = wait(lambda: (v if int((v := persistence(watch))['rdb_saves']) > int(before['rdb_saves'])
                                     and v['rdb_bgsave_in_progress'] == '0' else None), 'scheduled RDB complete')
                assert int(after['rdb_saves']) == int(before['rdb_saves']) + 1
                assert after['aof_rewrite_in_progress'] == '0'
            finally:
                if watch is not conn:
                    watch.close()
    check('BGSAVE during rewrite', save_during_rewrite)
    check('SAVE during rewrite', lambda: save_during_rewrite(True))
    assert not failures, '\n'.join(failures)


def errors(args):
    failures = []
    expected = RespError('MISCONF Errors writing to the AOF file: File too large')
    for policy, reorder in ((p, r) for p in ('no', 'everysec') for r in (0, 1)):
        try:
            extra = ['--appendonly', 'yes', '--appendfsync', policy]
            if not args.oracle:
                extra += ['--reorder', str(reorder), '--read-local', str(reorder if args.mode == '1s' else 0)]
            with boot(args, f'write-error-{policy}-{reorder}', extra, fsize=131072) as (process, conn, data):
                library = """#!lua name=persistfix2
redis.register_function{function_name='persistfix2_read', flags={'no-writes'},
 callback=function(keys, args) return redis.call('GET', keys[1]) end}
redis.register_function('persistfix2_write',
 function(keys, args) return redis.call('SET', keys[1], 'refused') end)
"""
                assert command(conn, 'FUNCTION', 'LOAD', library) == b'persistfix2'
                assert conn.must('SET', 'acknowledged-write', 'before') == b'OK'
                assert command(conn, 'FCALL', 'persistfix2_read', '1', 'acknowledged-write') == b'before'
                def persisted_increment():
                    files = list((data / 'appendonlydir').glob('*.incr.*'))
                    if len(files) != 1:
                        return None
                    contents = files[0].read_bytes()
                    return files[0] if b'acknowledged-write' in contents and b'before' in contents else None
                increment = wait(persisted_increment, 'acknowledged write reached increment')
                limit = increment.stat().st_size
                resource.prlimit(process.pid, resource.RLIMIT_FSIZE, (limit, 131072))
                emit('durability window armed', policy=policy, reorder=reorder, file_limit=limit)
                queued = Conn('127.0.0.1', args.port, timeout=15)
                read_only = Conn('127.0.0.1', args.port, timeout=15)
                try:
                    assert queued.must('WATCH', 'acknowledged-write') == b'OK'
                    assert queued.must('MULTI') == b'OK'
                    assert queued.must('SET', 'queued-write', 'value') == b'QUEUED'
                    assert read_only.must('MULTI') == b'OK'
                    assert read_only.must('GET', 'acknowledged-write') == b'QUEUED'
                    assert read_only.must('FCALL', 'persistfix2_read', '1', 'acknowledged-write') == b'QUEUED'
                    conn.send('SET', 'durability-window', b'v' * 200000)
                    emit('durability window', policy=policy, initial_reply=conn.read())
                    wait(lambda: persistence(conn)['aof_last_write_status'] == 'err',
                         'AOF write error observed')
                    for words in [('PING',), ('PING', 'value'), ('SET', 'refused-write', 'value'),
                                  ('MSET', 'refused-one', '1', 'refused-two', '2'),
                                  ('DEL', 'acknowledged-write')]:
                        reply = command(conn, *words)
                        if reply != expected:
                            failures.append(f'{policy} {words}: {reply!r}')
                    assert command(conn, 'GET', 'acknowledged-write') == b'before'
                    assert command(conn, 'MGET', 'refused-write', 'refused-one', 'refused-two') == [None] * 3
                    assert command(conn, 'PFCOUNT', 'absent-hll') == 0
                    assert command(conn, 'EVAL_RO', "return redis.call('GET', KEYS[1])", '1', 'acknowledged-write') == b'before'
                    for verb in ('FCALL', 'FCALL_RO'):
                        assert command(conn, verb, 'persistfix2_read', '1', 'acknowledged-write') == b'before'
                        assert command(conn, verb, 'persistfix2_write', '1', 'refused-function-write') == expected
                    assert command(conn, 'GET', 'refused-function-write') is None
                    assert command(queued, 'EXEC') == RespError(
                        'EXECABORT Transaction discarded because of: MISCONF Errors writing to the AOF file: File too large')
                    assert command(queued, 'EXEC') == RespError('ERR EXEC without MULTI')
                    assert command(conn, 'GET', 'queued-write') is None
                    assert command(read_only, 'EXEC') == [b'before', b'before']
                    assert conn.must('MULTI') == b'OK'
                    assert command(conn, 'SET', 'queue-error', 'value') == expected
                    assert command(conn, 'EXEC') == RespError('EXECABORT Transaction discarded because of previous errors.')
                    emit('AOF error refusal', policy=policy, info=persistence(conn))
                finally:
                    queued.close()
                    read_only.close()
        except Exception as error:
            emit('assertion', policy=policy, error=str(error))
            failures.append(f'{policy}: {error}')
    assert not failures, '\n'.join(failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('lastsave', 'shutdown', 'commands', 'errors'), required=True)
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
