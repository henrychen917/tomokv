#!/usr/bin/env python3
"""IO4.1 abort branch, deterministic and hook-free: gdb holds the FLIP coordinator thread at
Server::flip_complete_active (non-stop mode, so every other thread keeps running), idle
connections close while it is held, then the coordinator continues.

PRE: a surviving IO already acknowledged RoleReady with count == quota, its count then drops, and
flip_complete_active() reaches std::abort() (SIGABRT). POST: from its IoDrain acknowledgement every
IO holds closes before they leave its connection set, so the counts still equal the quotas, the
FLIP answers OK, and the held closes finish (and are reaped) once it retires.

Manual lane evidence (needs gdb and the binary's debug info); not a gate row.
Usage: flipfix_abort_probe.py --binary B --port P --cores C --output DIR [--net-io uring|epoll]
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from _lib import Conn, RespError, wait_ready


def emit(**values):
    print(json.dumps(values, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--idle', type=int, default=200)
    parser.add_argument('--closes', type=int, default=40)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    hit, released = out / 'coordinator-held', out / 'closes-done'
    script = out / 'probe.gdb'
    # A Python breakpoint holds ONLY the coordinator thread (non-stop mode): stop() blocks until
    # the driver's closes are done, then returns False so gdb resumes that thread.
    script.write_text('\n'.join([
        'set pagination off', 'set confirm off', 'set non-stop on',
        'set breakpoint pending on', 'handle SIGPIPE nostop noprint pass',
        'handle SIGTERM nostop noprint pass', 'handle SIGINT nostop noprint pass',
        'python', 'import os, time',
        'class Hold(gdb.Breakpoint):',
        '    def stop(self):',
        f'        open({str(hit)!r}, "w").close()',
        f'        while not os.path.exists({str(released)!r}):',
        '            time.sleep(0.01)',
        '        return False',
        'def on_stop(event):',
        '    if isinstance(event, gdb.SignalEvent) and event.stop_signal == "SIGABRT":',
        '        gdb.execute("bt 8")',
        'gdb.events.stop.connect(on_stop)',
        "Hold('tomo::Server::flip_complete_active')",
        "Hold('tomo_db0::Server::flip_complete_active')",
        'end',
        # Non-stop `run` returns to the prompt; gdb then keeps serving events from its stdin
        # pipe (held open below) until the driver ends the session.
        'run']) + '\n')
    directory = out / 'data'
    directory.mkdir()
    log = (out / 'server.log').open('w')
    argv = ['taskset', '-c', args.cores, 'gdb', '-nx', '-q', '-x', str(script), '--args',
            str(args.binary.resolve()), '--bind', '127.0.0.1', '--port', str(args.port),
            '--dir', str(directory), '--save', '', '--appendonly', 'no', '--thread-mode', '2s',
            '--ratio', '6:2', '--shards', '16', '--net-io', args.net_io]
    emit(event='boot', argv=argv, loadavg=os.getloadavg())
    gdb = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
    result = {}
    try:
        admin = wait_ready('127.0.0.1', args.port, timeout=90)
        admin.sock.settimeout(30)
        idle = [socket.create_connection(('127.0.0.1', args.port), timeout=10)
                for _ in range(args.idle)]
        for peer in idle:
            peer.sendall(b'*1\r\n$4\r\nPING\r\n')
            assert peer.recv(16) == b'+PONG\r\n'
        row = admin.must('FLIP')
        shape = dict(zip(row[::2], row[1::2]))
        total = shape[b'live_io'] + shape[b'live_ex']
        target = max(1, total // 4)          # 6:2 -> 2:6 converts surviving-IO peers away
        admin.send('FLIP', target, total - target)
        deadline = time.monotonic() + 60
        admin.sock.setblocking(False)
        while not hit.exists():
            try:
                early = admin.sock.recv(4096, socket.MSG_PEEK)
            except BlockingIOError:
                early = b''
            assert not early, f'FLIP answered before the hold: {early!r}'
            assert time.monotonic() < deadline, 'coordinator never reached flip_complete_active'
            assert gdb.poll() is None, 'gdb/server exited before the hold'
            time.sleep(.01)
        admin.sock.setblocking(True)
        admin.sock.settimeout(30)
        # The coordinator is held after every IO acknowledged RoleReady. Close peers now; the IO
        # threads run and see the EOFs.
        for _ in range(args.closes):
            idle.pop().close()
        time.sleep(.5)
        released.touch()
        try:
            reply = admin.read()
            result['reply'] = 'OK' if reply == b'OK' else (
                reply.message.decode() if isinstance(reply, RespError) else repr(reply))
        except (EOFError, ConnectionError, OSError) as error:
            result['reply'] = f'connection lost: {type(error).__name__}'
        time.sleep(.5)
        result['server_alive'] = 'exited normally' not in (out / 'server.log').read_text() and \
            'SIGABRT' not in (out / 'server.log').read_text()
        if result['reply'] == 'OK':
            admin.sock.settimeout(10)
            deadline = time.monotonic() + 10
            while True:
                clients = int(next(line.split(b':')[1] for line in
                                   admin.must('INFO', 'CLIENTS').splitlines()
                                   if line.startswith(b'connected_clients:')))
                if clients == len(idle) + 1 or time.monotonic() > deadline:
                    break
                time.sleep(.05)
            result['connected_clients'] = clients
            result['expected_clients'] = len(idle) + 1
        for peer in idle:
            peer.close()
    finally:
        released.touch()
        if gdb.poll() is None:
            try:
                gdb.stdin.write(b'interrupt -a\nkill inferiors 1\nquit\n')
                gdb.stdin.close()
                gdb.wait(timeout=30)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                gdb.kill()
                gdb.wait()
        log.close()
    text = (out / 'server.log').read_text(errors='replace')
    result['sigabrt'] = 'SIGABRT' in text
    emit(event='result', **result)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    ok = result.get('reply') == 'OK' and not result['sigabrt'] and \
        result.get('connected_clients') == result.get('expected_clients')
    emit(result='PASS' if ok else 'FAIL')
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
