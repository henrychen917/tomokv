"""Owned correctness listeners and raw replies shared by the four IO regressions."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from _lib import Conn, RespError, encode


def arguments(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default=os.environ.get('GATE_DIFFER_ORACLE_BIN', '/home/user/Projects/redis74/src/redis-server'))
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--net-io', choices=('epoll', 'uring'), required=True)
    p.add_argument('--output', type=Path, required=True)
    return p


def emit(**values):
    print(json.dumps(values, sort_keys=True, default=lambda x: str(x)), flush=True)


class Listener:
    def __init__(self, args, name, oracle=False, extra=(), config=None, directory=None):
        self.port = args.port + int(oracle)
        self.directory = directory or args.output / name
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = open(args.output / (name + '.log'), 'ab')
        guard = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{self.port}'])
        assert not guard.strip(), f'port {self.port} already has a listener'
        command = ['taskset', '-c', args.cores, str(Path(args.oracle if oracle else args.binary).resolve())]
        if config is not None:
            command.append(str(config.resolve()))
        command += ['--bind', '127.0.0.1', '--port', str(self.port), '--dir', str(self.directory.resolve()),
                    '--save', '', '--appendonly', 'no', '--enable-debug-command', 'yes']
        if not oracle:
            command += ['--shards', '16', '--thread-mode', args.mode,
                        '--net-io', args.net_io, '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
            if args.mode == '2s':
                command += ['--ratio', args.ratio]
        command += list(extra)
        self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT)
        self.connections = []
        emit(boot=command, pid=self.process.pid)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert self.process.poll() is None, f'{name} exited: see {self.log.name}'
                try:
                    c = self.connect()
                    assert c.cmd('PING') == b'PONG'
                    c.close()
                    break
                except (ConnectionRefusedError, ConnectionResetError, EOFError, socket.timeout):
                    time.sleep(.01)
            else:
                raise AssertionError(f'{name} never became ready')
        except BaseException:
            self.close()
            raise

    def connect(self):
        c = Conn('127.0.0.1', self.port, timeout=20)
        self.connections.append(c)
        return c

    def close(self):
        for c in self.connections:
            c.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                raise AssertionError(f'owned server did not stop: {self.log.name}')
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def info(c, section='all'):
    return dict(line.split(b':', 1) for line in c.cmd('INFO', section).splitlines()
                if b':' in line and not line.startswith(b'#'))


def cpu_times(pid):
    # schedstat's first field is actual on-CPU nanoseconds, independently of the server's counters.
    out = {}
    for task in Path(f'/proc/{pid}/task').iterdir():
        try:
            out[int(task.name)] = int((task / 'schedstat').read_text().split()[0])
        except FileNotFoundError:
            pass
    return out
