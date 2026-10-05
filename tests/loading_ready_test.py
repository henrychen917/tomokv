#!/usr/bin/env python3
"""Serverless readiness controls; today's TomoKV never sends LOADING.

The original eight GT13 cases retain mocked LOADING peers to lock compatibility.
The additional controls cover mainline PONG, a single deadline, and strict errors.
No server, listener, or socket is started.
"""
import errno
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import _lib


class Readiness(unittest.TestCase):
    def conn(self, *answers):
        conn = Mock()
        replies = iter(answers)
        def reply(*args):
            value = next(replies)
            if isinstance(value, (OSError, EOFError)):
                raise value
            return value
        conn.cmd.side_effect = reply
        return conn

    def test_loading_then_pong_closes_only_refused_peer(self):
        loading = self.conn(_lib.RespError(_lib.LOADING_REPLY))
        ready = self.conn(b'PONG')
        with patch.object(_lib, 'Conn', side_effect=[loading, ready]):
            self.assertIs(_lib.wait_ready('127.0.0.1', 1, timeout=1), ready)
        loading.close.assert_called_once()
        ready.close.assert_not_called()

    def test_never_loading_complete_fails_bounded(self):
        def loading(*args, **kw):
            return self.conn(_lib.RespError(_lib.LOADING_REPLY))
        with patch.object(_lib, 'Conn', side_effect=loading):
            with self.assertRaisesRegex(TimeoutError, 'LOADING'):
                _lib.wait_ready('127.0.0.1', 1, timeout=.05)

    def test_reset_and_eof_are_boot_retries(self):
        reset = self.conn(ConnectionResetError('boot reset'))
        eof = self.conn(EOFError('boot close'))
        ready = self.conn(b'PONG')
        with patch.object(_lib, 'Conn', side_effect=[reset, eof, ready]):
            self.assertIs(_lib.wait_ready('127.0.0.1', 1, timeout=1), ready)
        reset.close.assert_called_once()
        eof.close.assert_called_once()

    def test_unrelated_error_is_not_retried(self):
        conn = self.conn(_lib.RespError(b'NOAUTH Authentication required.'))
        with patch.object(_lib, 'Conn', return_value=conn) as make:
            with self.assertRaisesRegex(AssertionError, 'NOAUTH'):
                _lib.wait_ready('127.0.0.1', 1, timeout=1)
        self.assertEqual(make.call_count, 1)
        conn.close.assert_called_once()

    def test_banner_absence_never_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'server.log'
            log.write_text('listening on 127.0.0.1:10\n')
            with patch.object(_lib, 'Conn', side_effect=AssertionError('connected early')):
                with self.assertRaisesRegex(TimeoutError, 'banner absent'):
                    _lib.wait_ready('127.0.0.1', 1, timeout=.03, log_path=log)

    def test_owned_pid_required(self):
        proc = Mock(pid=123, returncode=None)
        proc.poll.return_value = None
        peer = self.conn(b'PONG', b'# Server\r\nprocess_id:999\r\n')
        with patch.object(_lib, 'Conn', return_value=peer):
            with self.assertRaisesRegex(AssertionError, 'PID mismatch'):
                _lib.wait_ready('127.0.0.1', 1, timeout=1, process=proc)
        peer.close.assert_called_once()

    def test_banner_and_owned_peer(self):
        proc = Mock(pid=123, returncode=None)
        proc.poll.return_value = None
        peer = self.conn(b'PONG', b'# Server\r\nprocess_id:123\r\n')
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'server.log'
            log.write_text('listening on 127.0.0.1:1\n')
            with patch.object(_lib, 'Conn', return_value=peer):
                self.assertIs(_lib.wait_ready('127.0.0.1', 1, timeout=1,
                                             process=proc, log_path=log), peer)

    def test_dead_child_does_not_connect(self):
        proc = Mock(pid=123, returncode=7)
        proc.poll.return_value = 7
        with patch.object(_lib, 'Conn', side_effect=AssertionError('connected to dead child')):
            with self.assertRaisesRegex(RuntimeError, 'status 7'):
                _lib.wait_ready('127.0.0.1', 1, process=proc)


class DeadlineAndIdentity(unittest.TestCase):
    conn = Readiness.conn

    def test_mainline_pong_needs_no_loading_phase(self):
        peer = self.conn(b'PONG')
        with patch.object(_lib, 'Conn', return_value=peer):
            self.assertIs(_lib.wait_ready('127.0.0.1', 1), peer)
        peer.cmd.assert_called_once_with('PING')
        peer.close.assert_not_called()
        self.assertIsNone(peer._read_deadline)

    def test_only_exact_loading_is_retryable(self):
        for reply in (b'OK', None, _lib.RespError(b'ERR startup failed'),
                      _lib.RespError(_lib.LOADING_REPLY + b'.'),
                      _lib.RespError(b'LOADING'), _lib.RespError(b'NOAUTH no')):
            with self.subTest(reply=reply):
                peer = self.conn(reply)
                with patch.object(_lib, 'Conn', return_value=peer) as connect:
                    with self.assertRaises(AssertionError):
                        _lib.wait_ready('127.0.0.1', 1)
                connect.assert_called_once()
                peer.close.assert_called_once()

    def test_non_transport_oserror_is_not_retried(self):
        for error in (PermissionError(errno.EACCES, 'denied'),
                      OSError(errno.EMFILE, 'descriptor exhaustion')):
            with self.subTest(error=error):
                peer = self.conn(error)
                with patch.object(_lib, 'Conn', return_value=peer) as connect:
                    with self.assertRaises(type(error)):
                        _lib.wait_ready('127.0.0.1', 1)
                connect.assert_called_once()
                peer.close.assert_called_once()

    def test_connection_refusal_then_mainline_pong(self):
        ready = self.conn(b'PONG')
        with patch.object(_lib, 'Conn', side_effect=[ConnectionRefusedError(), ready]):
            self.assertIs(_lib.wait_ready('127.0.0.1', 1, timeout=1), ready)

    def test_banner_must_be_an_exact_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'fresh.log'
            for text in ('prefix listening on 127.0.0.1:1\n',
                         'listening on 127.0.0.1:1 suffix\n',
                         'listening on 127.0.0.1:1'):
                log.write_text(text)
                with patch.object(_lib, 'Conn') as connect:
                    with self.assertRaisesRegex(TimeoutError, 'banner absent'):
                        _lib.wait_ready('127.0.0.1', 1, timeout=.01, log_path=log)
                connect.assert_not_called()

    def test_pid_missing_is_a_failure(self):
        proc = Mock(pid=123)
        proc.poll.return_value = None
        peer = self.conn(b'PONG', b'# Server\r\n')
        with patch.object(_lib, 'Conn', return_value=peer):
            with self.assertRaisesRegex(AssertionError, 'PID mismatch'):
                _lib.wait_ready('127.0.0.1', 1, process=proc)
        peer.close.assert_called_once()

    def test_shell_pid_is_checked_and_verified(self):
        for actual in (123, 999):
            peer = self.conn(b'PONG', f'process_id:{actual}\r\n'.encode())
            with patch.object(_lib.os, 'kill') as alive, \
                    patch.object(_lib, 'Conn', return_value=peer):
                if actual == 123:
                    self.assertIs(_lib.wait_ready('127.0.0.1', 1, pid=123), peer)
                else:
                    with self.assertRaisesRegex(AssertionError, 'PID mismatch'):
                        _lib.wait_ready('127.0.0.1', 1, pid=123)
            alive.assert_any_call(123, 0)

    def test_child_exit_during_handshake_fails(self):
        proc = Mock(pid=123)
        proc.poll.side_effect = [None, 7]
        peer = self.conn(b'PONG', b'process_id:123\r\n')
        with patch.object(_lib, 'Conn', return_value=peer):
            with self.assertRaisesRegex(RuntimeError, 'status 7'):
                _lib.wait_ready('127.0.0.1', 1, process=proc)
        peer.close.assert_called_once()

    def test_connection_and_handshake_share_one_deadline(self):
        now = [0.0]
        proc = Mock(pid=123)
        proc.poll.return_value = None
        peer = Mock()
        def connect(*args, **kw):
            self.assertEqual(kw['timeout'], .5)
            now[0] += .4
            return peer
        def reply(*args):
            if args == ('PING',):
                now[0] += .07
                return b'PONG'
            self.assertEqual(args, ('INFO', 'SERVER'))
            self.assertAlmostEqual(peer.sock.settimeout.call_args.args[0], .03)
            now[0] += .04
            return b'process_id:123\r\n'
        peer.cmd.side_effect = reply
        with patch.object(_lib.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(_lib.time, 'sleep'), patch.object(_lib, 'Conn', side_effect=connect):
            with self.assertRaisesRegex(TimeoutError, 'deadline'):
                _lib.wait_ready('127.0.0.1', 1, timeout=.5, process=proc)
        peer.close.assert_called_once()
        self.assertEqual(peer.cmd.call_count, 2)

    def test_connect_exhausting_deadline_sends_no_ping(self):
        now = [0.0]
        peer = Mock()
        def connect(*args, **kw):
            now[0] = 1
            return peer
        with patch.object(_lib.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(_lib.time, 'sleep'), patch.object(_lib, 'Conn', side_effect=connect):
            with self.assertRaises(TimeoutError):
                _lib.wait_ready('127.0.0.1', 1, timeout=.5)
        peer.cmd.assert_not_called()
        peer.close.assert_called_once()

    def test_partial_line_and_bulk_cannot_renew_deadline(self):
        for operation in ('line', 'bulk'):
            with self.subTest(operation=operation):
                now = [0.0]
                peer = object.__new__(_lib.Conn)
                peer.sock, peer.file = Mock(), Mock()
                peer._read_deadline = .05
                def drip(size):
                    now[0] += .02
                    return b'x'
                peer.file.read1.side_effect = drip
                with patch.object(_lib.time, 'monotonic', side_effect=lambda: now[0]):
                    with self.assertRaisesRegex(TimeoutError, 'deadline'):
                        peer._line() if operation == 'line' else peer._read(100)
                self.assertEqual(peer.file.read1.call_count, 3)

    def test_real_resp_reader_resets_deadline_for_application(self):
        peer = object.__new__(_lib.Conn)
        peer.sock = Mock()
        peer.file = io.BytesIO(b'+PONG\r\n$16\r\nprocess_id:123\r\n\r\n+OK\r\n')
        proc = Mock(pid=123)
        proc.poll.return_value = None
        with patch.object(_lib, 'Conn', return_value=peer):
            ready = _lib.wait_ready('127.0.0.1', 1, process=proc)
        self.assertIs(ready, peer)
        self.assertIsNone(peer._read_deadline)
        self.assertEqual(ready.cmd('SET', 'after', 'ready'), b'OK')
        self.assertEqual(peer.sock.sendall.call_count, 3)


if __name__ == '__main__':
    unittest.main()
