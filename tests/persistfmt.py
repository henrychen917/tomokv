#!/usr/bin/env python3
"""D9/D17c/S1 directed witnesses. Invoked by gate.sh, with its CPU/port geometry.

Every case uses fresh state, owns its children, and records the oracle transcript.
Stream comparisons omit only physical radix-tree statistics and XPENDING's elapsed
idle milliseconds; XINFO FULL checks the persisted absolute timestamps exactly.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import select
import signal
import time

import aoffix2 as h


@contextmanager
def server(oracle=False, extra=(), data=None, **kwargs):
    old_binary, old_oracle = h.ARGS.binary, h.ARGS.oracle
    h.ARGS.binary = ARGS.oracle_binary if oracle else ARGS.binary
    h.ARGS.oracle = oracle
    try:
        with h.Server(['--enable-debug-command', 'yes', *extra], data=data, **kwargs) as s:
            assert s.ready, s.logpath.read_text(errors='replace')
            yield s, s.client()
    finally:
        h.ARGS.binary, h.ARGS.oracle = old_binary, old_oracle


def pairs(items):
    assert len(items) % 2 == 0, items
    return dict(zip(items[::2], items[1::2]))


def state(c, key):
    full = pairs(c.cmd('XINFO', 'STREAM', key, 'FULL', 'COUNT', 0))
    physical = {k: full.pop(k) for k in (b'radix-tree-keys', b'radix-tree-nodes')}
    groups = []
    pending = []
    for raw in full[b'groups']:
        g = pairs(raw)
        g[b'consumers'] = sorted((pairs(x) for x in g[b'consumers']), key=lambda x: x[b'name'])
        groups.append(g)
        p = c.cmd('XPENDING', key, g[b'name'])
        detail = c.cmd('XPENDING', key, g[b'name'], '-', '+', 1000)
        pending.append([g[b'name'], p, [[x[0], x[1], x[3]] for x in detail]])
    full[b'groups'] = sorted(groups, key=lambda x: x[b'name'])
    result = [full, sorted(pending)]
    h.emit('stream_state', key=key, full=result, physical=physical)
    return result


def populate(c):
    keys = ['s:groups', 's:trim', 's:empty', 's:plain']
    for key in keys:
        for n in range(1, 9):
            fields = [b'f\x00', b'v\xff' + str(n).encode(), 'integer', str(n)]
            if n % 2:
                fields += ['other', 'x' * 150]
            assert c.cmd('XADD', key, f'{n}-0', *fields) == f'{n}-0'.encode()
    for key in keys[:3]:
        assert c.cmd('XGROUP', 'CREATE', key, 'g', '0', 'ENTRIESREAD', 0) == b'OK'
        assert c.cmd('XGROUP', 'CREATE', key, 'unread', '$') == b'OK'
        for name in ('alice', 'bob', 'empty'):
            assert c.cmd('XGROUP', 'CREATECONSUMER', key, 'g', name) == 1
        for name in ('alice', 'bob'):
            assert len(c.cmd('XREADGROUP', 'GROUP', 'g', name, 'COUNT', 3,
                             'STREAMS', key, '>')[0][1]) == 3
        assert c.cmd('XCLAIM', key, 'g', 'bob', 0, '1-0', 'TIME', 100000,
                     'RETRYCOUNT', 7, 'JUSTID') == [b'1-0']
        assert c.cmd('XDEL', key, '2-0', '5-0') == 2
    assert c.cmd('XTRIM', 's:trim', 'MINID', '=', '4-0') == 2
    assert c.cmd('XTRIM', 's:empty', 'MAXLEN', '=', 0) == 6
    return keys


def stream_roundtrip():
    # Run the same assertions on the reference, including empty streams with a PEL.
    for oracle in (True, False):
        with server(oracle, data=ARGS.artifacts / ('oracle' if oracle else 'target')) as (_, c):
            for key in populate(c):
                expected = state(c, key)
                payload = c.cmd('DUMP', key)
                assert isinstance(payload, bytes) and len(payload) > 10
                assert c.cmd('RESTORE', key + ':copy', 0, payload) == b'OK'
                assert state(c, key + ':copy') == expected


def stream_interchange():
    for source_oracle in (True, False):
        direction = 'redis-to-tomo' if source_oracle else 'tomo-to-redis'
        with server(source_oracle, data=ARGS.artifacts / (direction + '-source')) as (_, c):
            images = [(key, state(c, key), c.cmd('DUMP', key)) for key in populate(c)]
        with server(not source_oracle, data=ARGS.artifacts / (direction + '-destination')) as (_, c):
            for key, expected, payload in images:
                (ARGS.artifacts / (direction + '-' + key.replace(':', '-') + '.dump')).write_bytes(payload)
                assert c.cmd('RESTORE', key, 0, payload) == b'OK'
                assert state(c, key) == expected, direction


def crc64(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x95ac9329ac4bc9b5 if crc & 1 else 0)
    return crc


def envelope(body, version=12):
    data = body + version.to_bytes(2, 'little')
    return data + crc64(data).to_bytes(8, 'little')


def result(c, *args):
    try:
        return c.cmd(*args)
    except RuntimeError as exc:
        return ('error', str(exc))


def stream_options():
    with server(True, data=ARGS.artifacts / 'source') as (_, c):
        populate(c)
        payload = c.cmd('DUMP', 's:groups')
    transcripts = []
    for oracle in (True, False):
        with server(oracle, data=ARGS.artifacts / ('oracle' if oracle else 'target')) as (_, c):
            rows = []
            for options in ([], ['REPLACE'], ['ABSTTL'], ['IDLETIME', 42], ['FREQ', 17],
                            ['IDLETIME', -1], ['FREQ', 256], ['IDLETIME', 'x'],
                            ['IDLETIME', 1, 'FREQ', 1], ['unknown']):
                c.cmd('DEL', 'copy')
                rows.append(result(c, 'RESTORE', 'copy', 0, payload, *options))
            assert c.cmd('RESTORE', 'copy', 0, payload, 'REPLACE') == b'OK'
            rows.append(result(c, 'RESTORE', 'copy', 0, payload))
            assert c.cmd('RESTORE', 'copy', 1, payload, 'REPLACE', 'ABSTTL') == b'OK'
            rows.append(c.cmd('EXISTS', 'copy'))
            assert c.cmd('RESTORE', 'copy', 60000, payload) == b'OK'
            assert 0 < c.cmd('PTTL', 'copy') <= 60000
            # Envelope errors and CRC-correct structural errors have distinct replies.
            corrupt = [b'', payload[:-1], payload[:-1] + bytes([payload[-1] ^ 1]),
                       envelope(payload[:-10], 13), envelope(bytes([21])),
                       envelope(bytes([21, 1, 0]))]
            for bad in corrupt:
                rows.append(result(c, 'RESTORE', 'copy', 0, bad, 'REPLACE'))
                assert c.cmd('TYPE', 'copy') == b'stream'
            h.emit('restore_transcript', oracle=oracle, replies=rows)
            transcripts.append(rows)
    assert transcripts[0] == transcripts[1], transcripts


SOURCES = [b"#!lua name=one\nredis.register_function('f_one', function() return 'one' end)",
           b"#!lua name=two\nredis.register_function{function_name='f_two', callback=function() return 2 end, flags={'no-writes'}, description='two'}"]


def libraries(c):
    return sorted(c.cmd('FUNCTION', 'LIST', 'WITHCODE'), key=lambda x: pairs(x)[b'library_name'])


def functions():
    case = ARGS.case
    for oracle in (True, False):
        data = ARGS.artifacts / ('oracle' if oracle else 'target')
        opt = []
        if case.startswith('aof-'):
            opt = ['--appendonly', 'yes', '--appendfsync', 'always',
                   '--aof-use-rdb-preamble', case[4:], '--auto-aof-rewrite-percentage', '0']
        with server(oracle, opt, data) as (s, c):
            for source in SOURCES:
                assert c.cmd('FUNCTION', 'LOAD', source) in (b'one', b'two')
            expected = libraries(c)
            assert len(expected) == 2
            assert c.cmd('SET', 'sentinel', 'saved') == b'OK'
            if case == 'save':
                assert c.cmd('SAVE') == b'OK'
            elif case == 'bgsave':
                assert c.cmd('BGSAVE') == b'Background saving started'
                deadline = time.monotonic() + 10
                while c.info()['rdb_bgsave_in_progress'] != '0':
                    assert time.monotonic() < deadline, 'BGSAVE did not finish'
                    time.sleep(.01)
                assert c.info()['rdb_last_bgsave_status'] == 'ok'
            elif case == 'shutdown':
                c.send('SHUTDOWN', 'SAVE')
                try:
                    c.read()
                    raise AssertionError('SHUTDOWN must close the connection')
                except EOFError:
                    pass
                assert s.p.wait(timeout=10) == 0
            elif case == 'reload':
                assert c.cmd('DEBUG', 'RELOAD') == b'OK'
                assert libraries(c) == expected
                assert c.cmd('FUNCTION', 'FLUSH') == b'OK'
                assert c.cmd('DEBUG', 'RELOAD', 'NOSAVE') == b'OK'
                assert libraries(c) == expected
                assert result(c, 'DEBUG', 'RELOAD', 'NOFLUSH')[0] == 'error'
                assert c.cmd('DEBUG', 'RELOAD', 'NOSAVE', 'NOFLUSH', 'MERGE') == b'OK'
            elif case.startswith('aof-'):
                assert c.cmd('BGREWRITEAOF') == b'Background append only file rewriting started'
                h.wait_rewrite(c, 'aof_rewrites')
            else:
                raise AssertionError(case)
            h.emit('functions_before_restart', oracle=oracle, libraries=expected)
            # SIGKILL ensures the restart tests the requested operation, not shutdown's save.
            if s.p.poll() is None:
                s.stop(signal.SIGKILL)
        with server(oracle, opt, data) as (_, c):
            assert c.cmd('GET', 'sentinel') == b'saved'
            got = libraries(c)
            h.emit('functions_after_restart', oracle=oracle, libraries=got)
            assert got == expected, (oracle, got, expected)
            assert c.cmd('FCALL', 'f_one', 0) == b'one'
            assert c.cmd('FCALL_RO', 'f_two', 0) == 2


def aof_failure():
    # Reuse the exact existing RLIMIT_FSIZE fault. Fill stderr's pipe after boot
    # to hold fail() at its first diagnostic: PRE has already cleared recording_.
    # A connection on another IO thread must remain gated throughout that window.
    rfd, wfd = os.pipe()
    try:
        with server(extra=h.aof('always'), fsize=128 * 1024, stderr_fd=wfd) as (s, _):
            c = h.off_writer(s)
            assert c.cmd('SET', 'before', 'ok') == b'OK'
            os.set_blocking(wfd, False)
            try:
                while True:
                    os.write(wfd, b'x' * 4096)
            except BlockingIOError:
                pass
            os.set_blocking(wfd, True)
            c.send('SET', 'full', b'z' * 200000)
            try:
                deadline = time.monotonic() + 4
                while True:
                    blocked = [p for p in Path(f'/proc/{s.p.pid}/task').glob('*/wchan')
                               if 'pipe_write' in p.read_text()]
                    if blocked:
                        break
                    assert time.monotonic() < deadline, 'fail() logging window never opened'
                    time.sleep(.005)
                h.emit('failure_window_armed', threads=[str(p.parent) for p in blocked])
                readable, _, _ = select.select([c.s], [], [], .5)
                assert not readable, f'failed write acknowledged: {c.read()!r}'
            finally:
                os.set_blocking(rfd, False)
                while True:
                    try:
                        if not os.read(rfd, 65536):
                            break
                    except BlockingIOError:
                        break
            assert s.p.wait(timeout=4) == 1
            try:
                reply = c.read()
                raise AssertionError(f'failed write acknowledged after release: {reply!r}')
            except (EOFError, OSError):
                pass
    finally:
        os.close(rfd)
        os.close(wfd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=['stream-roundtrip', 'stream-interchange', 'stream-options',
                                       'save', 'bgsave', 'shutdown', 'reload', 'aof-yes', 'aof-no',
                                       'aof-failure', 'aof-repeat'])
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--oracle-binary', type=Path, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--mode', choices=['1s', '2s'], required=True)
    parser.add_argument('--engine', choices=['epoll', 'uring'], required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=1)
    ARGS = parser.parse_args()
    ARGS.binary = ARGS.binary.resolve()
    ARGS.oracle = False
    ARGS.policy = 'always'
    ARGS.artifacts.mkdir(parents=True, exist_ok=True)
    os.environ['LC_ALL'] = 'C'
    h.ARGS = ARGS
    if ARGS.case.startswith('stream-'):
        globals()[ARGS.case.replace('-', '_')]()
    elif ARGS.case == 'aof-failure':
        aof_failure()
    elif ARGS.case == 'aof-repeat':
        root = ARGS.artifacts
        for n in range(ARGS.repeats):
            ARGS.artifacts = root / str(n)
            ARGS.artifacts.mkdir()
            h.error()
        ARGS.artifacts = root
        h.emit('repeated_error_row', passed=ARGS.repeats, failures=0)
    else:
        functions()
    print('PASS persistfmt', ARGS.case, ARGS.mode, ARGS.engine)
