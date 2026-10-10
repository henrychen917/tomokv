#!/usr/bin/env python3
"""IO4.1/IO4.2/IO4.4/CT4.3: owned boots, bounded windows, fatal sanitizer reports.

Adapted from round4-read/tests/io-loop/t05f and t05g. No throughput conclusions.
Every invocation owns its exact process, port and fresh persistence directory.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

from _lib import Conn, RespError, encode, wait_ready


def emit(**values):
    print(json.dumps(values, sort_keys=True), flush=True)


def report(conn):
    row = conn.must('FLIP')
    return dict(zip(row[::2], row[1::2]))


@contextlib.contextmanager
def boot(args, label, save='', directory=None, extra=()):
    directory = directory or args.output / label
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (label + '.log')
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', args.port)) != 0, 'owned port already busy'
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(directory),
            '--save', save, '--appendonly', 'no', '--thread-mode', '2s',
            '--ratio', args.ratio, '--shards', '16', '--net-io', args.net_io,
            '--enable-debug-command', 'yes', *extra]
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1', TSAN_OPTIONS='halt_on_error=1:exitcode=66')
    emit(event='boot', argv=argv, affinity=sorted(os.sched_getaffinity(0)),
         loadavg=os.getloadavg())
    (directory / (label + '.argv.json')).write_text(json.dumps(argv) + '\n')
    (directory / (label + '.load.txt')).write_text(subprocess.run(
        ['ps', '-eLo', 'pid,tid,psr,pcpu,comm'], capture_output=True, text=True,
        check=True).stdout)
    with path.open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        conn = None
        try:
            conn = wait_ready('127.0.0.1', args.port, timeout=25, process=process, log_path=path)
            conn.sock.settimeout(6.5)
            emit(event='ready', pid=process.pid, exe=os.readlink(f'/proc/{process.pid}/exe'))
            yield conn, process, directory
        finally:
            if conn:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            emit(event='stop', rc=process.returncode, log=str(path), loadavg=os.getloadavg())
    text = path.read_text(errors='replace')
    assert not any(s in text for s in ('ERROR: AddressSanitizer', 'ThreadSanitizer:',
                                      'runtime error:')), text[-12000:]
    assert process.returncode in (0, 1), f'unclean process exit {process.returncode}: {text[-4000:]}'


def conn(args):
    return Conn('127.0.0.1', args.port, timeout=6.5)


def disconnects(args, churn=False):
    with boot(args, 'churn' if churn else 'close') as (admin, process, _):
        idle = []
        observer = conn(args)
        stop = threading.Event()
        workers = []
        outcomes = {}
        witnessed = 0
        def connector():
            while not stop.is_set():
                peer = None
                try:
                    peer = Conn('127.0.0.1', args.port, timeout=.2)
                    peer.cmd('PING')
                except (OSError, EOFError):
                    pass  # Accept-side drops during FLIP are outside this regression.
                finally:
                    if peer:
                        peer.close()
        try:
            for _ in range(1500):
                idle.append(conn(args))
            for peer in idle:
                assert peer.must('PING') == b'PONG'
            shape = report(admin)
            total = shape[b'live_io'] + shape[b'live_ex']
            shapes = [max(2, total // 4), total // 2, total * 3 // 4, total // 2]
            if churn:
                workers = [threading.Thread(target=connector) for _ in range(6)]
                for worker in workers:
                    worker.start()
            for attempt in range(args.attempts):
                target = shapes[attempt % len(shapes)]
                admin.send('FLIP', target, total - target)
                moving = report(observer)[b'moving']
                witnessed += bool(moving)
                for _ in range(10):
                    if idle:
                        idle.pop().close()
                    time.sleep(.0002)
                start = time.monotonic()
                reply = admin.read()
                assert reply == b'OK' or isinstance(reply, RespError), reply
                outcomes[str(reply)] = outcomes.get(str(reply), 0) + 1
                assert not report(observer)[b'moving'], 'FLIP reply preceded retirement'
                assert admin.must('PING') == b'PONG'
                assert process.poll() is None, 'server crashed'
                emit(attempt=attempt, reply=str(reply), moving=moving,
                     elapsed=time.monotonic() - start)
                time.sleep(.02)
            assert witnessed, 'no FLIP window witnessed; missing arming is a failure'
        finally:
            stop.set()
            for worker in workers:
                worker.join(2)
                assert not worker.is_alive(), 'connector did not stop'
            for peer in idle:
                peer.close()
            observer.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            raw = admin.must('INFO', 'CLIENTS')
            clients = int(next(line.split(b':')[1] for line in raw.splitlines()
                               if line.startswith(b'connected_clients:')))
            if clients == 1:
                break
            time.sleep(.02)
        assert clients == 1, f'closed connections not reaped: {clients}'
        emit(result='PASS', case=args.case, witnessed=witnessed, outcomes=outcomes)


def stopping(args):
    with boot(args, args.case, save='3600 1') as (admin, process, directory):
        admin.raw(b''.join(encode('SET', f'flipfix:{i}', 'durable') for i in range(1000)))
        assert [admin.read() for _ in range(1000)] == [b'OK'] * 1000
        observer, blocker = conn(args), conn(args)
        try:
            blocker.send('BLPOP', 'flipfix:blocker', 0)
            deadline = time.monotonic() + 2
            while b'blocked_clients:1' not in observer.must('INFO', 'CLIENTS'):
                assert time.monotonic() < deadline, 'blocking operation did not arm'
            shape = report(observer)
            total = shape[b'live_io'] + shape[b'live_ex']
            target = total // 2 if shape[b'live_io'] != total // 2 else max(2, total // 4)
            admin.send('FLIP', target, total - target)
            deadline = time.monotonic() + 2
            while not report(observer)[b'moving']:
                assert time.monotonic() < deadline, 'FLIP drain window did not open'
            emit(event='armed', case=args.case, moving=1, acknowledged=1000)
            start = time.monotonic()
            process.send_signal(signal.SIGTERM if args.case == 'sigterm' else signal.SIGINT)
            if args.case == 'sigint':
                time.sleep(.02)
                assert process.poll() is None, 'first signal did not leave an observable pending stop'
                process.send_signal(signal.SIGINT)
            status = process.wait(timeout=3 if args.case == 'sigterm' else .75)
            assert status == (0 if args.case == 'sigterm' else 1), status
            emit(event='signal-exit', elapsed=time.monotonic() - start, status=status)
        finally:
            blocker.close()
            observer.close()
    if args.case == 'sigterm':
        with boot(args, 'restart', directory=directory) as (admin, _, _):
            admin.raw(b''.join(encode('GET', f'flipfix:{i}') for i in range(1000)))
            assert [admin.read() for _ in range(1000)] == [b'durable'] * 1000
            emit(result='PASS', case=args.case, recovered=1000)
    else:
        emit(result='PASS', case=args.case)


def controllers(args):
    with boot(args, 'controllers', extra=['--flip-auto', '1']) as (admin, _, _):
        peer = conn(args)
        try:
            for i in range(20000):
                assert peer.must('PING') == b'PONG'
                if i % 20 == 0:
                    admin.must('DEBUG', 'FLIPCTL')
                    admin.must('DEBUG', 'LBSIGNALS')
            # Monitor's sampled fingerprint reader runs on its one-second beat.
            for _ in range(5):
                time.sleep(1)
                assert peer.must('PING') == b'PONG'
                admin.must('DEBUG', 'FLIPCTL')
                admin.must('DEBUG', 'LBSIGNALS')
        finally:
            peer.close()
        emit(result='PASS', case=args.case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=('close', 'churn', 'sigterm', 'sigint', 'controllers'))
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--attempts', type=int, default=30)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.case in ('close', 'churn'):
        disconnects(args, args.case == 'churn')
    elif args.case == 'controllers':
        controllers(args)
    else:
        stopping(args)


if __name__ == '__main__':
    main()
