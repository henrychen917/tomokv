#!/usr/bin/env python3
"""Directed live PS1/PS2 witnesses. MAINLINE ONLY; starts disposable owned servers.

The kill case holds the executor after recording the marker SET and before post.
An old-code ACK orders the in-window SIGKILL; a fixed server must first be released
to post/fsync. The term case signals while that same window is held and other
connections have a recorded acknowledged prefix. All acknowledged keys, plus the
executed marker, must replay. Every run uses a new private data directory.
"""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import threading
import time

from shutdown_report import load_report, require_persistence


def encode(*args):
    parts = [str(arg).encode() if not isinstance(arg, bytes) else arg for arg in args]
    return b'*%d\r\n' % len(parts) + b''.join(b'$%d\r\n' % len(p) + p + b'\r\n' for p in parts)


class Resp:
    def __init__(self, port, timeout=10):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.sock.makefile('rb')

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError('server closed')
        tag, payload = line[:1], line[1:-2]
        if tag == b'+': return payload
        if tag == b'-': raise AssertionError(payload.decode(errors='replace'))
        if tag == b':': return int(payload)
        if tag == b'$':
            n = int(payload)
            if n == -1: return None
            value = self.stream.read(n)
            assert self.stream.read(2) == b'\r\n', 'bulk trailer'
            return value
        if tag == b'*':
            n = int(payload)
            return None if n == -1 else [self.read() for _ in range(n)]
        raise AssertionError('invalid RESP')

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def close(self):
        self.stream.close()
        self.sock.close()


def wait_for(predicate, message, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, message
        time.sleep(.005)


def guard_port(port):
    # The gate has reaped its previous server, but its accepted connections can
    # still be in TIME_WAIT. Match listener restart semantics without REUSEPORT:
    # a live listener must continue to refuse this bind.
    with socket.socket() as guard:
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        guard.bind(('127.0.0.1', port))


class Run:
    def __init__(self, args):
        import tempfile
        self.args = args
        args.artifacts.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=f'{args.mode}-{args.case}-', dir=args.artifacts))
        self.window = self.root / 'window'
        self.process = None
        self.log = None
        self.clients = []
        self.boots = 0

    def marker(self, suffix):
        return self.window.with_suffix('.' + suffix)

    def record(self, event, **fields):
        with (self.root / 'processes.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event=event, time_ns=time.time_ns(), boot=self.boots,
                pid=self.process.pid, port=self.args.port, **fields)) + '\n')

    def identify(self, client, event):
        raw = client.cmd('INFO', 'Server')
        assert isinstance(raw, bytes), 'persistence peer INFO is not a bulk reply'
        info = dict(line.split(':', 1) for line in raw.decode().splitlines() if ':' in line)
        observed = info.get('process_id')
        self.record(event, observed_pid=observed)
        assert observed == str(self.process.pid), (
            f'persistence peer PID mismatch on port {self.args.port}: '
            f'owned={self.process.pid}, observed={observed}; {self.root / "processes.jsonl"}')

    def ready(self):
        assert self.process.poll() is None, f'boot failed: {self.log_path}'
        client = None
        try:
            client = Resp(self.args.port, timeout=.1)
            self.identify(client, 'ready')
            assert self.process.poll() is None, f'boot exited after INFO: {self.log_path}'
            return True
        except (OSError, EOFError) as error:
            # TCP connect alone can precede any response from the new child.
            # Require a protocol reply from its PID, including after SIGKILL.
            if client is not None:
                self.record('unanswered_peer', error=repr(error))
            return False
        finally:
            if client is not None: client.close()

    def client(self):
        client = Resp(self.args.port)
        try:
            self.identify(client, 'client')
        except BaseException:
            client.close()
            raise
        self.clients.append(client)
        return client

    def boot(self, hook):
        self.boots += 1
        self.log_path = self.root / f'server-{self.boots}.log'
        self.log = self.log_path.open('wb')
        env = dict(os.environ)
        env.pop('TOMO_AOF_ACK_WINDOW', None)
        if hook: env['TOMO_AOF_ACK_WINDOW'] = str(self.window.resolve())
        argv = ['taskset', '-c', self.args.cores, str(self.args.binary.resolve()),
                '--bind', '127.0.0.1', '--port', str(self.args.port), '--shards', '16',
                '--protected-mode', 'no', '--thread-mode', self.args.mode,
                '--appendonly', 'yes', '--appendfsync', 'always', '--save', '',
                '--auto-aof-rewrite-percentage', '0', '--enable-debug-command', 'yes',
                '--dir', str(self.root.resolve()), '--net-io', self.args.net_io]
        if self.args.mode == '2s': argv += ['--ratio', self.args.ratio]
        self.process = subprocess.Popen(argv, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.record('spawn', argv=argv, log=str(self.log_path))
        wait_for(self.ready, f'owned server did not answer INFO: {self.log_path}', 30)

    def reap(self, expected):
        status = self.process.wait(timeout=20)
        self.record('reap', status=status)
        self.log.close()
        assert status == expected, f'exit {status}, wanted {expected}: {self.log_path}'
        for client in self.clients:
            client.close()
        self.clients.clear()
        self.process = None

    def cleanup(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        for client in self.clients:
            client.close()
        if self.log: self.log.close()


def exercise(args):
    run = Run(args)
    expected = {}
    stopped = threading.Event()
    errors = []
    workers = []
    try:
        run.boot(hook=True)
        warm = run.client()
        for i in range(64):
            assert warm.cmd('SET', f'persistfix:warm:{i}', i) == b'OK'
        persistence = warm.cmd('INFO', 'Persistence').decode()
        waits = dict(line.split(':', 1) for line in persistence.splitlines() if ':' in line)
        assert int(waits.get('aof_send_gate_waits', '0')) > 0, 'AOF reply gate window never fired'

        if args.case == 'term':
            lock = threading.Lock()
            def writer(worker):
                client = run.client()
                try:
                    i = 0
                    while not stopped.is_set():
                        keys = [f'persistfix:load:{worker}:{i+j}' for j in range(32)]
                        client.sock.sendall(b''.join(encode('SET', key, key) for key in keys))
                        for key in keys:
                            assert client.read() == b'OK'
                            with lock: expected[key] = key.encode()
                        i += 32
                except (EOFError, OSError):
                    if not stopped.is_set(): errors.append('writer disconnected before SIGTERM')
                except Exception as error:
                    errors.append(repr(error))
            for worker in range(4):
                thread = threading.Thread(target=writer, args=(worker,))
                workers.append(thread)
                thread.start()
            wait_for(lambda: len(expected) >= args.count or errors, 'acknowledged prefix never reached N')
            assert not errors, errors

        # In 1s the writer is also an executor. Reroll with a fresh key until a
        # different producer owns the held chunk, so writer-close can race it.
        for attempt in range(32):
            for suffix in ('entered', 'release', 'kill'):
                run.marker(suffix).unlink(missing_ok=True)
            victim_key = f'persistfix:window:{attempt}'
            victim = run.client()
            victim.sock.sendall(encode('SET', victim_key, 'durable-witness'))
            wait_for(lambda: run.marker('entered').exists() and
                     len(run.marker('entered').read_text().split()) == 2,
                     'executor did not enter pre-post window')
            producer, writer_tid = map(int, run.marker('entered').read_text().split())
            if producer != writer_tid:
                break
            run.marker('release').touch()
            assert victim.read() == b'OK'
            expected[victim_key] = b'durable-witness'
        else:
            raise AssertionError('fresh arming never held a non-writer producer')
        assert run.process.poll() is None, 'process died before the in-window decision'
        in_window_ack = bool(select.select([victim.sock], [], [], .5)[0])
        if in_window_ack:
            assert victim.read() == b'OK'
        if args.case == 'kill':
            if in_window_ack:
                run.marker('kill').touch()  # executor raises SIGKILL inside the unposted window
            else:
                run.marker('release').touch()
                assert victim.read() == b'OK'
                os.kill(run.process.pid, signal.SIGKILL)  # no trailing INFO/round trip
            expected[victim_key] = b'durable-witness'
            run.reap(-signal.SIGKILL)
        else:
            assert all(t.is_alive() for t in workers), 'SIGTERM must interrupt active writers'
            stopped.set()  # disconnects after the signal are now expected
            os.kill(run.process.pid, signal.SIGTERM)
            wait_for(lambda: run.marker('stopping').exists(), 'writer never entered shutdown')
            # Give the broken writer a deterministic close notification; a fixed writer
            # cannot close while the marker's producer is held. No success is inferred
            # from this timeout: recovery and the report are both mandatory below.
            until = time.monotonic() + .25
            while not run.marker('closed').exists() and time.monotonic() < until:
                time.sleep(.005)
            run.marker('release').touch()
            for thread in workers: thread.join(timeout=15)
            assert not any(t.is_alive() for t in workers), 'load workers failed to stop'
            assert not errors, errors
            run.reap(0)
            report = load_report(run.log_path)
            require_persistence(report, enabled=True)
            assert report['persistence']['records_written'] >= len(expected), 'record witness too small'
            # This separately witnesses the terminal owner flush, even when PS1's fix
            # prevented acknowledging the held marker before SIGTERM.
            expected[victim_key] = b'durable-witness'

        (run.root / 'acknowledged.json').write_text(json.dumps(
            {'in_window_ack': in_window_ack, 'keys': sorted(expected), 'case': args.case}, indent=2))
        run.boot(hook=False)
        recovered = run.client()
        for key, value in expected.items():
            assert recovered.cmd('GET', key) == value, f'acknowledged/executed write lost on reload: {key}'
        # PS1 old 2s must both enter the window and lose the ACKed marker. A 1s
        # baseline has no local ack-before-post window and is a required regression arm.
        assert not in_window_ack, 'acknowledgement observed while producer was held before post'
        os.kill(run.process.pid, signal.SIGTERM)
        run.reap(0)
        require_persistence(load_report(run.log_path), enabled=True)
        print(f'PASS persistfix {args.case} {args.mode} {args.net_io}: '
              f'window=entered in_window_ack={in_window_ack} recovered={len(expected)} '
              f'gate_waits={waits["aof_send_gate_waits"]} artifacts={run.root}')
    finally:
        stopped.set()
        run.marker('release').touch()
        run.cleanup()
        for thread in workers: thread.join(timeout=10)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--case', choices=('kill', 'term'), required=True)
    p.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--cores', default='0-7')
    p.add_argument('--ratio', default='3')
    p.add_argument('--port', type=int, default=16379)
    p.add_argument('--count', type=int, default=1024)
    p.add_argument('--artifacts', type=Path, default=Path('build/persistfix-live'))
    args = p.parse_args()
    assert args.count > 0
    guard_port(args.port)
    exercise(args)
