"""Owned correctness listeners and byte-preserving RESP2 clients for compat2."""
import contextlib
import json
from pathlib import Path
import socket
import subprocess
import time


class Client:
    def __init__(self, port, context=None):
        self.s = socket.create_connection(('127.0.0.1', port), 5)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if context:
            self.s = context.wrap_socket(self.s, server_hostname='localhost')
        self.f = self.s.makefile('rb')

    def send(self, *args):
        args = [x if isinstance(x, bytes) else str(x).encode() for x in args]
        self.s.sendall(b'*%d\r\n' % len(args) + b''.join(
            b'$%d\r\n' % len(x) + x + b'\r\n' for x in args))

    def read(self):
        line = self.f.readline()
        if not line:
            raise EOFError('server closed connection')
        assert line.endswith(b'\r\n'), line
        tag, value = line[:1], line[1:-2]
        if tag == b'-':
            return line
        if tag == b'+':
            return value
        if tag == b':':
            return int(value)
        if tag == b'$':
            if int(value) < 0:
                return None
            data = self.f.read(int(value))
            assert len(data) == int(value) and self.f.read(2) == b'\r\n'
            return data
        if tag == b'*':
            return None if int(value) < 0 else [self.read() for _ in range(int(value))]
        raise AssertionError(line)

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def close(self):
        self.f.close()
        self.s.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def clean(value):
    if isinstance(value, bytes):
        return value.decode(errors='backslashreplace')
    if isinstance(value, (tuple, list)):
        return [clean(x) for x in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    return value


def save(path, value):
    Path(path).write_text(json.dumps(clean(value), indent=2) + '\n')


def stats(c):
    return {k: int(v) for line in c.cmd('INFO', 'stats').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)] if v.isdigit()}


def wait_for(predicate, message, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(.002)
    raise AssertionError(message)


@contextlib.contextmanager
def server(binary, directory, port, cores, mode='2s', engine='uring', extra=(), oracle=False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    assert not subprocess.check_output(['ss', '-ltnH', f'sport = :{port}']).strip()
    command = ['taskset', '-c', cores, str(Path(binary).resolve()), '--bind', '127.0.0.1',
               '--port', str(port), '--dir', str(directory), '--save', '', '--appendonly', 'no',
               '--protected-mode', 'no', '--enable-debug-command', 'yes']
    if not oracle:
        command += ['--shards', '16', '--thread-mode', mode,
                    '--net-io', engine, '--key-lb', '0', '--client-lb', '0',
                    '--flip-auto', '0', '--read-local', '0', '--reorder', '0', '--databases', '16']
        if mode == '2s':
            command += ['--ratio', '6:2']
    command += list(extra)
    save(directory / 'command.json', command)
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            def ready():
                assert p.poll() is None, f'server exited: {directory}/server.log'
                try:
                    with Client(port) as c:
                        return c.cmd('PING') == b'PONG'
                except (OSError, EOFError):
                    return False
            wait_for(ready, 'server did not boot', 10)
            yield
        finally:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                raise AssertionError('server did not stop gracefully')
            assert p.returncode == 0, (command, p.returncode)


def arguments(parser):
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--engine', choices=('epoll', 'uring'), default='uring')
    parser.add_argument('--cores', required=True)
    parser.add_argument('--port', type=int, required=True)
