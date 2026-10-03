#!/usr/bin/env python3
"""SV2 live proof for mainline: owned, fresh directories; restart checks and NOSAVE control."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import signal
import socket
import subprocess
import time

from _lib import Conn, RespError
from _gate_process import info, require


@contextlib.contextmanager
def boot(args, directory, label, save=None):
    # The caller creates a fresh case directory, then reuses ONLY that directory for recovery.
    log_path = directory / (label + '.log')
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()), '--bind', '127.0.0.1',
            '--port', str(args.port), '--dir', str(directory), '--shards', '16',
            '--ratio', args.ratio, '--thread-mode', args.mode, '--net-io', args.net_io,
            '--appendonly', 'no']
    if save is not None:
        argv += ['--save', save]
    (directory / (label + '.argv.json')).write_text(json.dumps(argv) + '\n')
    with log_path.open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        conn = None
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                require(process.poll() is None, f'{label}: boot exited; see {log_path}')
                try:
                    conn = Conn('127.0.0.1', args.port, timeout=10)
                    row = info(conn, 'SERVER')
                    require(int(row['process_id']) == process.pid, 'port belongs to another process')
                    require(row['thread_mode'] == args.mode, 'booted requested thread mode')
                    break
                except (ConnectionRefusedError, ConnectionResetError):
                    if conn:
                        conn.close()
                    conn = None
                    time.sleep(.025)
            require(conn is not None, f'{label}: boot timeout; see {log_path}')
            yield conn, process
        finally:
            if conn:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def stop(conn, process, action):
    if action in ('sigterm', 'sigint'):
        process.send_signal(signal.SIGTERM if action == 'sigterm' else signal.SIGINT)
    else:
        conn.send('SHUTDOWN', *action)
    try:
        reply = conn.read()
    except (EOFError, ConnectionResetError):
        pass
    else:
        raise AssertionError(f'shutdown must close without a reply, got {reply!r}')
    require(process.wait(timeout=30) == 0, 'shutdown exits successfully')


def restart_case(args, name, action, expected_save, initial_save=None, config_save=None,
                 baseline=False):
    directory = args.output / name
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = directory / 'dump.tomo'
    with boot(args, directory, 'write', initial_save) as (conn, process):
        configured = conn.must('CONFIG', 'GET', 'save')[1]
        if initial_save is None:
            require(configured == b'3600 1 300 100 60 10000', 'default save schedule is armed')
        if config_save is not None:
            require(conn.must('CONFIG', 'SET', 'save', config_save) == b'OK', 'live save schedule applied')
        if baseline:
            require(conn.must('SET', 'sv2:baseline', 'old') == b'OK', 'baseline write acknowledged')
            require(conn.must('SAVE') == b'OK', 'baseline snapshot completed')
        before = snapshot.read_bytes() if snapshot.exists() else None
        require(baseline or before is None, 'fresh state: no periodic snapshot before witness')
        require(conn.must('SET', 'sv2:new', 'durable-value') == b'OK', 'new write acknowledged')
        require(conn.must('GET', 'sv2:new') == b'durable-value', 'new value visible before stop')
        # A prior/periodic snapshot cannot satisfy the recovery assertion accidentally.
        require((snapshot.read_bytes() if snapshot.exists() else None) == before,
                'snapshot did not capture the witness before shutdown')
        stop(conn, process, action)
    after = snapshot.read_bytes() if snapshot.exists() else None
    with boot(args, directory, 'restart', '') as (conn, process):
        got = conn.must('GET', 'sv2:new')
        require(got == (b'durable-value' if expected_save else None),
                f'{name}: acknowledged write recovered after restart (got {got!r})')
        if baseline:
            require(conn.must('GET', 'sv2:baseline') == b'old', 'NOSAVE preserves prior snapshot')
        stop(conn, process, ['NOSAVE'])
    require((after is not None and after != before) if expected_save else after == before,
            f'{name}: shutdown snapshot choice')
    print(f'{args.mode} {name}: PASS (restart, save={expected_save}, '
          f'snapshot={hashlib.sha256(after).hexdigest() if after else "absent"})', flush=True)


def failed_save(args):
    directory = args.output / 'save-failure'
    directory.mkdir(parents=True, exist_ok=False)
    with boot(args, directory, 'write') as (conn, process):
        require(conn.must('SET', 'sv2:new', 'still-live') == b'OK', 'failure witness written')
        # Even root cannot rename a regular snapshot over a directory. No permission-dependent skip.
        blocker = directory / 'dump.tomo'
        blocker.mkdir()
        reply = conn.cmd('SHUTDOWN')
        require(isinstance(reply, RespError) and b'Errors trying to SHUTDOWN' in reply.message,
                'failed final save refuses shutdown')
        require(process.poll() is None and conn.must('GET', 'sv2:new') == b'still-live',
                'failed final save preserves serving data')
        blocker.rmdir()
        stop(conn, process, ['NOSAVE'])
    print(f'{args.mode} save-failure: PASS (error and continued service)', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--cores', default='0-7')
    parser.add_argument('--port', default=7899, type=int)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--case', choices=('command', 'sigterm', 'sigint', 'all'), default='all')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    # Refuse occupied ports before starting an owned process or issuing any command.
    with socket.socket() as probe:
        require(probe.connect_ex(('127.0.0.1', args.port)) != 0, 'test port must be unused')
    if args.case in ('command', 'all'):
        restart_case(args, 'default', [], True)
        restart_case(args, 'nosave', ['NOSAVE'], False, baseline=True)
        restart_case(args, 'save-override', ['SAVE'], True, initial_save='')
        restart_case(args, 'save-off', [], False, initial_save='')
        restart_case(args, 'config-off', [], False, config_save='')
        restart_case(args, 'config-on', [], True, initial_save='', config_save='3600 1')
        failed_save(args)
    for action in ('sigterm', 'sigint'):
        if args.case in (action, 'all'):
            restart_case(args, action, action, True)
            restart_case(args, action + '-off', action, False, initial_save='')


if __name__ == '__main__':
    main()
