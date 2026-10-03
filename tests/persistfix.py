#!/usr/bin/env python3
"""Directed live PS1/PS2 witnesses. MAINLINE ONLY; starts disposable owned servers.

The kill case holds the executor after recording the marker SET and before post.
An old-code ACK orders the in-window SIGKILL; a fixed server must first be released
to post/fsync. The term case signals while that same window is held and other
connections have a recorded acknowledged prefix. All acknowledged keys, plus the
executed marker, must replay. Every run uses a new private data directory.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

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


def listening_inodes(port):
    inodes = set()
    for table in ('tcp', 'tcp6'):
        path = Path('/proc/net') / table
        if table == 'tcp6' and not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == '0A' and int(fields[1].rsplit(':', 1)[1], 16) == port:
                inodes.add(fields[9])
    return inodes


def process_cmdline(pid):
    try:
        return (Path('/proc') / str(pid) / 'cmdline').read_bytes().replace(
            b'\0', b' ').decode(errors='replace').strip() or '<empty cmdline>'
    except OSError as error:
        return f'<cmdline unavailable: {error}>'


class PortOwnershipError(OSError):
    pass


def check_port_owner(port, expected_pid=None):
    """Check every reuseport listener, including IPv6; never probe a foreign one."""
    inodes = listening_inodes(port)
    if not inodes:
        return False
    found = set()
    foreign = []
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue  # The process may close a descriptor during the scan.
                if target.startswith('socket:[') and target[8:-1] in inodes:
                    found.add(target[8:-1])
                    pid = int(process.name)
                    if pid != expected_pid:
                        foreign.append(f'pid={pid} cmdline={process_cmdline(pid)!r}')
                        break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    if foreign:
        raise PortOwnershipError(errno.EADDRINUSE,
            f'foreign process owns port {port}: ' + '; '.join(foreign))
    # A listener can disappear during the scan. A still-live but unreadable
    # owner is a failure, never permission to connect to an unidentified server.
    unknown = (inodes - found) & listening_inodes(port)
    if unknown:
        raise PortOwnershipError(errno.EADDRINUSE,
            f'cannot identify owner of port {port}: socket inodes {sorted(unknown)}; '
            'pid/cmdline unavailable through /proc')
    return bool(found)


def guard_port(port):
    # The gate has reaped its previous server, but its accepted connections can
    # still be in TIME_WAIT. Match listener restart semantics without REUSEPORT:
    # a live listener must continue to refuse this bind.
    check_port_owner(port)
    with socket.socket() as guard:
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            guard.bind(('127.0.0.1', port))
        except OSError:
            check_port_owner(port)  # Diagnose a listener racing the preflight.
            raise


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
        self.identity = {}
        self.exit_status = None
        self.last_probe = ''

    def marker(self, suffix):
        return self.window.with_suffix('.' + suffix)

    def client(self):
        client = Resp(self.args.port)
        self.clients.append(client)
        return client

    def save_identity(self):
        (self.root / f'server-{self.boots}.json').write_text(
            json.dumps(self.identity, indent=2) + '\n')

    def ready(self):
        owned = check_port_owner(self.args.port, self.process.pid)
        assert self.process.poll() is None, 'server exited during boot'
        # This file is newly created for this Popen PID, never a previous boot's
        # log. The banner itself has no PID; INFO binds it to the owned child.
        banner = f'listening on 127.0.0.1:{self.args.port}'
        if banner not in self.log_path.read_text(errors='replace').splitlines() or not owned:
            return False
        client = None
        try:
            client = Resp(self.args.port, timeout=.25)
            info = client.cmd('INFO', 'Server')
            assert isinstance(info, bytes), f'invalid INFO Server: {info!r}'
            fields = dict(line.split(':', 1) for line in info.decode().splitlines() if ':' in line)
            peer_pid = fields.get('process_id')
            self.identity['info'] = fields
            self.save_identity()
            if peer_pid != str(self.process.pid):
                command = process_cmdline(peer_pid) if peer_pid and peer_pid.isdecimal() else '<unknown>'
                raise PortOwnershipError(errno.EADDRINUSE,
                    f'foreign INFO identity on port {self.args.port}: pid={peer_pid!r} '
                    f'cmdline={command!r}; expected pid={self.process.pid}')
            assert client.cmd('PING') == b'PONG', 'identity connection did not answer PING'
            assert check_port_owner(self.args.port, self.process.pid), 'owned listener disappeared'
            assert self.process.poll() is None, 'server exited during identity handshake'
            self.identity.update(ready=True, listening_banner=banner,
                                 info_run_id=fields.get('run_id'))
            self.save_identity()
            client.sock.settimeout(10)
            self.clients.append(client)
            self.ready_client = client
            client = None
            return True
        except PortOwnershipError:
            raise  # Never retry into a foreign process, even if it speaks RESP.
        except (OSError, EOFError) as error:
            self.last_probe = repr(error)
            check_port_owner(self.args.port, self.process.pid)
            assert self.process.poll() is None, 'server exited during identity handshake'
            return False
        finally:
            if client is not None:
                client.close()

    def boot(self, hook):
        self.boots += 1
        self.exit_status = None
        self.last_probe = ''
        self.log_path = self.root / f'server-{self.boots}.log'
        self.log = self.log_path.open('xb')
        # INFO Server currently has process_id but no run_id. Keep the harness
        # boot UUID explicitly separate from any future server-supplied run_id.
        self.identity = dict(run_id=uuid.uuid4().hex, run_id_source='persistfix boot UUID',
                             pid=None, ready=False, exit_status=None, log=str(self.log_path))
        self.save_identity()
        guard_port(self.args.port)  # Both the initial boot and recovery own a fresh slot.
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
        self.identity.update(pid=self.process.pid, argv=argv)
        self.save_identity()
        wait_for(self.ready, 'server did not establish listening/INFO/PING identity', 30)
        return self.ready_client

    def failure(self, error):
        status = self.exit_status
        if self.process is not None:
            status = self.process.poll()
            if status is None:
                # A reset/EOF can precede waitpid visibility (including a core
                # dump). Observe the natural exit before cleanup sends SIGKILL.
                try:
                    status = self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self.identity.update(exit_status=status, failure=str(error), last_probe=self.last_probe)
        self.save_identity()
        with self.log_path.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 8192))
            tail = stream.read().decode(errors='replace').strip() or '<empty log>'
        label = 'recovered server' if self.boots > 1 else 'initial server'
        state = f'exited {status}' if status is not None else (
            'still running (exit_status=None)' if self.identity.get('pid') else 'not started (exit_status=None)')
        return (f'{label} {state}: {tail}\n'
                f'pid={self.identity.get("pid")} run_id={self.identity.get("run_id")} '
                f'log={self.log_path}\n{type(error).__name__}: {error}'
                + (f'\nlast identity probe: {self.last_probe}' if self.last_probe else ''))

    def reap(self, expected):
        status = self.process.wait(timeout=20)
        self.exit_status = status
        self.identity['exit_status'] = status
        self.save_identity()
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
        warm = run.boot(hook=True)
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
        recovered = run.boot(hook=False)
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
    except (Exception, SystemExit) as error:
        raise AssertionError(run.failure(error)) from None
    finally:
        stopped.set()
        run.marker('release').touch()
        run.cleanup()
        for thread in workers: thread.join(timeout=10)


def self_test():
    """Serverless fault schedules: no executable server or load generator."""
    import tempfile
    import unittest
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    module = sys.modules[__name__]
    build = Path(__file__).resolve().parents[1] / 'build'
    build.mkdir(exist_ok=True)

    class IdentityTests(unittest.TestCase):
        def setUp(self):
            temporary = tempfile.TemporaryDirectory(dir=build)
            self.addCleanup(temporary.cleanup)
            self.args = SimpleNamespace(artifacts=Path(temporary.name), mode='1s', case='kill',
                binary=Path('/unused-tomokv'), cores='112-127', ratio='6:2', port=16379, net_io='uring')
            self.run = Run(self.args)
            self.run.boots = 2
            self.run.log_path = self.run.root / 'server-2.log'
            self.run.log_path.write_text('')
            self.run.identity = dict(pid=4321, run_id='test-boot', ready=False)
            self.child = Mock(pid=4321)
            self.child.poll.return_value = None
            self.child.wait.side_effect = subprocess.TimeoutExpired('test child', 2)
            self.run.process = self.child
            # Any accidental live boot or network probe makes the self-test fail.
            self.addCleanup(patch.stopall)
            patch.object(subprocess, 'Popen', side_effect=AssertionError('self-test spawned a child')).start()
            patch.object(socket, 'create_connection', side_effect=AssertionError('self-test connected')).start()

        def banner(self):
            self.run.log_path.write_text(f'listening on 127.0.0.1:{self.args.port}\n')

        def client(self, pid=4321, pong=b'PONG', extra=''):
            client = Mock()
            client.cmd.side_effect = [f'# Server\r\nprocess_id:{pid}\r\n{extra}'.encode(), pong]
            return client

        def test_empty_and_wrong_logs_never_probe(self):
            for log in ('', 'listening on 127.0.0.1:16380\n',
                        'old listening on 127.0.0.1:16379\n'):
                with self.subTest(log=log), patch.object(module, 'check_port_owner', return_value=True), \
                        patch.object(module, 'Resp') as resp:
                    self.run.log_path.write_text(log)
                    self.assertFalse(self.run.ready())
                    resp.assert_not_called()

        def test_own_banner_and_info_ping_keep_the_same_connection(self):
            self.banner()
            client = self.client(extra='run_id:server-run-id\r\n')
            with patch.object(module, 'check_port_owner', return_value=True), \
                    patch.object(module, 'Resp', return_value=client):
                self.assertTrue(self.run.ready())
            self.assertEqual(client.cmd.call_args_list,
                             [(('INFO', 'Server'),), (('PING',),)])
            self.assertIs(self.run.ready_client, client)
            self.assertEqual(self.run.clients, [client])
            client.close.assert_not_called()
            identity = json.loads((self.run.root / 'server-2.json').read_text())
            self.assertEqual((identity['pid'], identity['run_id'], identity['info_run_id']),
                             (4321, 'test-boot', 'server-run-id'))
            self.assertTrue(identity['ready'])

        def test_banner_without_owned_listener_is_not_ready(self):
            self.banner()
            with patch.object(module, 'check_port_owner', return_value=False), \
                    patch.object(module, 'Resp') as resp:
                self.assertFalse(self.run.ready())
                resp.assert_not_called()

        def test_foreign_listener_fails_before_connection(self):
            for log in ('', 'listening on 127.0.0.1:16379\n'):
                self.run.log_path.write_text(log)
                with self.subTest(log=log), \
                        patch.object(module, 'check_port_owner', side_effect=PortOwnershipError(
                            errno.EADDRINUSE, 'foreign process: pid=99 cmdline=foreign-server')), \
                        patch.object(module, 'Resp') as resp:
                    with self.assertRaisesRegex(PortOwnershipError, 'pid=99 cmdline=foreign-server'):
                        self.run.ready()
                    resp.assert_not_called()

        def test_foreign_info_is_fatal_without_ping_or_retry(self):
            self.banner()
            client = self.client(pid=99)
            with patch.object(module, 'check_port_owner', return_value=True), \
                    patch.object(module, 'process_cmdline', return_value='foreign-server'), \
                    patch.object(module, 'Resp', return_value=client) as resp:
                with self.assertRaisesRegex(PortOwnershipError, "pid='99'.*foreign-server"):
                    self.run.ready()
            self.assertEqual(resp.call_count, 1)
            client.cmd.assert_called_once_with('INFO', 'Server')
            client.close.assert_called_once()

        def test_missing_identity_and_bad_ping_fail(self):
            self.banner()
            for replies, message in (([b'# Server\r\n', b'PONG'], 'foreign INFO identity'),
                                     ([b'process_id:4321\r\n', b'NO'], 'did not answer PING')):
                client = Mock()
                client.cmd.side_effect = replies
                with self.subTest(replies=replies), patch.object(module, 'check_port_owner', return_value=True), \
                        patch.object(module, 'Resp', return_value=client):
                    with self.assertRaisesRegex((OSError, AssertionError), message):
                        self.run.ready()
                self.assertFalse(self.run.identity['ready'])
                client.close.assert_called_once()

        def test_half_open_and_reset_probes_never_count_as_ready(self):
            self.banner()
            for error in (socket.timeout('half-open'), ConnectionResetError('reset'), EOFError('closed')):
                client = Mock()
                client.cmd.side_effect = error
                with self.subTest(error=error), patch.object(module, 'check_port_owner', return_value=True), \
                        patch.object(module, 'Resp', return_value=client):
                    self.assertFalse(self.run.ready())
                self.assertFalse(self.run.identity['ready'])
                client.close.assert_called_once()

        def test_foreign_arrival_after_handshake_is_fatal(self):
            self.banner()
            client = self.client()
            with patch.object(module, 'check_port_owner', side_effect=[True,
                    PortOwnershipError(errno.EADDRINUSE, 'foreign process: pid=99 cmdline=late-owner')]), \
                    patch.object(module, 'Resp', return_value=client):
                with self.assertRaisesRegex(PortOwnershipError, 'late-owner'):
                    self.run.ready()
            client.close.assert_called_once()

        def test_real_socket_owner_reports_pid_cmdline_and_refuses_boot(self):
            # A socket-only fixture, with no accept loop or server process.
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                self.assertTrue(check_port_owner(port, os.getpid()))
                with self.assertRaises(PortOwnershipError) as failure:
                    guard_port(port)
                self.assertIn(f'pid={os.getpid()}', str(failure.exception))
                self.assertIn(process_cmdline(os.getpid()), str(failure.exception))

        def test_both_boots_guard_and_record_distinct_identities(self):
            run = Run(self.args)
            clients = [self.client(pid=4321), self.client(pid=4322)]
            children = [Mock(pid=4321), Mock(pid=4322)]
            for child in children:
                child.poll.return_value = None
                child.wait.return_value = 0
            def start(*args, **kwargs):
                run.log_path.write_text(f'listening on 127.0.0.1:{self.args.port}\n')
                return children[run.boots - 1]
            try:
                with patch.object(module, 'guard_port') as guard, \
                        patch.object(subprocess, 'Popen', side_effect=start), \
                        patch.object(module, 'check_port_owner', return_value=True), \
                        patch.object(module, 'Resp', side_effect=clients):
                    self.assertIs(run.boot(True), clients[0])
                    run.reap(0)
                    self.assertIs(run.boot(False), clients[1])
                    run.reap(0)
                    self.assertEqual(guard.call_count, 2)
                records = [json.loads((run.root / f'server-{n}.json').read_text()) for n in (1, 2)]
                self.assertNotEqual(records[0]['run_id'], records[1]['run_id'])
                self.assertEqual([r['pid'] for r in records], [4321, 4322])
                self.assertTrue(all(r['ready'] and r['exit_status'] == 0 for r in records))
            finally:
                run.cleanup()

        def test_preflight_foreign_owner_never_spawns_at_either_boot(self):
            for boots in (0, 1):
                run = Run(self.args)
                run.boots = boots
                try:
                    with patch.object(module, 'guard_port', side_effect=PortOwnershipError(
                            errno.EADDRINUSE, 'foreign process: pid=99 cmdline=preflight')), \
                            patch.object(subprocess, 'Popen') as popen:
                        with self.assertRaisesRegex(PortOwnershipError, 'preflight'):
                            run.boot(False)
                        popen.assert_not_called()
                finally:
                    run.cleanup()

        def test_reload_crashes_show_status_and_tail_even_when_exit_is_delayed(self):
            for status, delayed, log in ((1, False, 'AOF load plan failed: broken\n'),
                                         (-11, True, 'reload crashed\n'), (-9, False, '')):
                self.child.poll.return_value = None if delayed else status
                self.child.wait.side_effect = None
                self.child.wait.return_value = status
                self.run.log_path.write_text(log)
                message = self.run.failure(ConnectionResetError('Connection reset by peer'))
                self.assertTrue(message.startswith(f'recovered server exited {status}: '
                                                    + (log.strip() or '<empty log>')), message)
                self.assertIn('pid=4321 run_id=test-boot', message)
                self.assertEqual(json.loads((self.run.root / 'server-2.json').read_text())['exit_status'], status)
                self.child.kill.assert_not_called()

        def test_live_assertion_and_reaped_report_failures_keep_original_reason(self):
            self.banner()
            message = self.run.failure(AssertionError('acknowledged/executed write lost on reload: key'))
            self.assertIn('still running (exit_status=None)', message)
            self.assertIn('acknowledged/executed write lost on reload: key', message)
            self.run.process = None
            self.run.exit_status = 0
            message = self.run.failure(SystemExit('persistence shutdown must drain'))
            self.assertIn('recovered server exited 0: listening on', message)
            self.assertIn('persistence shutdown must drain', message)

        def test_exercise_wraps_boot_get_and_report_failures(self):
            for stage in ('boot', 'get', 'lost-write', 'report'):
                with self.subTest(stage=stage):
                    self.run.boots = 0
                    self.run.process = self.child
                    self.child.poll.return_value = None
                    warm = Mock()
                    warm.cmd.side_effect = lambda *args: (
                        b'aof_send_gate_waits:1\r\n' if args[0] == 'INFO' else b'OK')
                    victim = Mock()
                    victim.read.return_value = b'OK'
                    victim.sock.sendall.side_effect = lambda data: self.run.marker('entered').write_text('1 0')
                    recovered = Mock()
                    recovered.cmd.return_value = b'durable-witness' if stage == 'report' else None
                    def crash(*args):
                        self.child.poll.return_value = -11
                        self.run.log_path.write_text('reload crash witness\n')
                        raise ConnectionResetError('Connection reset by peer')
                    if stage == 'get':
                        recovered.cmd.side_effect = crash
                    def boot(hook):
                        self.run.boots += 1
                        if hook:
                            return warm
                        if stage == 'boot':
                            crash()
                        return recovered
                    def reap(expected):
                        if self.run.boots == 2:
                            self.run.process = None
                            self.run.exit_status = 0
                    with patch.object(module, 'Run', return_value=self.run), \
                            patch.object(self.run, 'boot', side_effect=boot), \
                            patch.object(self.run, 'client', return_value=victim), \
                            patch.object(self.run, 'reap', side_effect=reap), \
                            patch.object(self.run, 'cleanup'), patch.object(os, 'kill'), \
                            patch.object(select, 'select', return_value=([], [], [])), \
                            patch.object(module, 'load_report', return_value={}), \
                            patch.object(module, 'require_persistence', side_effect=SystemExit(
                                'persistence shutdown must drain')):
                        with self.assertRaises(AssertionError) as failure:
                            exercise(self.args)
                    message = str(failure.exception)
                    if stage in ('boot', 'get'):
                        self.assertTrue(message.startswith('recovered server exited -11: reload crash witness'), message)
                    else:
                        self.assertIn('recovered server ', message)
                        self.assertIn('acknowledged/executed write lost on reload:' if stage == 'lost-write'
                                      else 'persistence shutdown must drain', message)

    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(IdentityTests)).wasSuccessful()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--self-test', action='store_true', help='serverless identity/failure schedules')
    live = '--self-test' not in sys.argv
    p.add_argument('--binary', type=Path, required=live)
    p.add_argument('--mode', choices=('1s', '2s'), required=live)
    p.add_argument('--case', choices=('kill', 'term'), required=live)
    p.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--cores', default='0-7')
    p.add_argument('--ratio', default='3')
    p.add_argument('--port', type=int, default=16379)
    p.add_argument('--count', type=int, default=1024)
    p.add_argument('--artifacts', type=Path, default=Path('build/persistfix-live'))
    args = p.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    assert args.count > 0
    exercise(args)
