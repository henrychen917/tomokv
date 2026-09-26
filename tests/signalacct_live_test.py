#!/usr/bin/env python3
"""Serverless live-driver orchestration checks; no subprocess or socket is opened."""
import argparse
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import signalacct_live as live


class Driver(unittest.TestCase):
    def args(self, directory, **kw):
        return argparse.Namespace(binary=Path('/never-executed'), output=Path(directory),
            cores='0-7', port=16739, mode=kw.get('mode', '2s'), read_local=1, overlap=1,
            reorder=1, databases=1, net_io='uring', edges=True, legacy_control=kw.get('legacy', False))

    def attempt(self, args, report, *, boot_failed=False):
        proc = mock.Mock()
        proc.returncode = 0
        proc.poll.return_value = 0 if boot_failed else None
        proc.wait.side_effect = lambda **kw: setattr(proc.poll, 'return_value', 0)
        conn = mock.Mock()
        conn.cmd.side_effect = lambda *v: b'PONG' if v == ('PING',) else b'OK'
        with (mock.patch.object(live.subprocess, 'Popen', return_value=proc) as spawn,
              mock.patch.object(live, 'Conn', return_value=conn),
              mock.patch.object(live, 'productive') as productive,
              mock.patch.object(live, 'wait_parked', return_value={'112': 'io_uring'}),
              mock.patch.object(live, 'load_report', return_value=report),
              contextlib.redirect_stderr(io.StringIO())):
            result = live.attempt(args, 1)
        return result, spawn.call_args.args[0], conn, productive, proc

    @staticmethod
    def report(mode):
        first = dict(entry_ns=100, begin_ns=101, end_ns=233, exit_ns=234,
                     busy_ns=112, idle_ns=20, did_submit=1, sweep_submit=1, park=1,
                     role_exit=mode == '2s', stopped=mode == '1s')
        second = dict(first, entry_ns=400, begin_ns=401, end_ns=533, exit_ns=534,
                      role_exit=False, stopped=True)
        return dict(schema=1, thread_mode=mode, threads=[dict(tid=0, role='io' if mode == '2s' else 'fused',
            busy_ns=224, idle_ns=40, io_tenures=[first, second] if mode == '2s' else [first])])

    def test_modes_use_exact_gate_geometry_and_numeric_flip_grammar(self):
        for mode in ('1s', '2s'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=live.ROOT / 'build') as directory:
                result, argv, conn, traffic, proc = self.attempt(self.args(directory, mode=mode), self.report(mode))
                self.assertGreater(result['tenures'], 0)
                self.assertEqual(argv[argv.index('--shards') + 1], '16')
                self.assertEqual('--ratio' in argv, mode == '2s')
                if mode == '2s':
                    self.assertEqual(argv[argv.index('--ratio') + 1], '6:2')
                    self.assertIn(mock.call('FLIP', 3, 5), conn.cmd.call_args_list)
                    self.assertIn(mock.call('FLIP', 6, 2), conn.cmd.call_args_list)
                self.assertEqual(traffic.call_count, 3 if mode == '2s' else 1)
                proc.send_signal.assert_called_once_with(live.signal.SIGTERM)

    def test_legacy_control_requires_the_accounting_failure(self):
        with tempfile.TemporaryDirectory(dir=live.ROOT / 'build') as directory:
            report = self.report('2s')
            report['threads'][0]['io_tenures'][0]['busy_ns'] -= 40
            result, *_ = self.attempt(self.args(directory, legacy=True), report)
            self.assertEqual(result['legacy_control'], 'REJECTED')
            with self.assertRaisesRegex(AssertionError, 'legacy dropped-window accounting was accepted'):
                self.attempt(self.args(directory, legacy=True), self.report('2s'))
            with self.assertRaisesRegex(AssertionError, 'boot failed'):
                self.attempt(self.args(directory, legacy=True), report, boot_failed=True)

    def test_unentered_window_has_exactly_three_fresh_attempts_then_fails(self):
        argv = ['signalacct_live.py', '--binary', '/never-executed', '--output', 'build/mock',
                '--mode', '2s', '--read-local', '1', '--overlap', '1', '--reorder', '1']
        with (mock.patch.object(live.sys, 'argv', argv),
              mock.patch.object(live, 'attempt', side_effect=SystemExit('window never opened')) as attempt):
            with self.assertRaisesRegex(AssertionError, 'after three fresh boots'):
                live.main()
            self.assertEqual([c.args[1] for c in attempt.call_args_list], [1, 2, 3])
        with (mock.patch.object(live.sys, 'argv', argv),
              mock.patch.object(live, 'attempt', side_effect=SystemExit('completed interval is not exact')) as attempt):
            with self.assertRaisesRegex(SystemExit, 'not exact'):
                live.main()
            self.assertEqual(attempt.call_count, 1)

    def test_flip_records_actual_wire_and_elapsed_for_errors_and_unexpected_replies(self):
        for wire, classification in ((b'+OK\r\n', 'ok'),
                (b'-ERR a FLIP is already in progress\r\n', 'server-error'),
                (b'-ERR FLIP connection ownership count is not conserved\r\n', 'server-error'),
                (b'$2\r\nNO\r\n', 'unexpected-reply')):
            with self.subTest(wire=wire), tempfile.TemporaryDirectory(dir=live.ROOT / 'build') as directory:
                conn = live.Conn.__new__(live.Conn)
                conn.file = io.BytesIO(wire)
                conn.send = mock.Mock()
                events = []
                with mock.patch.object(live.time, 'monotonic_ns', side_effect=[10, 345]):
                    if classification == 'ok':
                        live.manual_flip(conn, 6, 2, Path(directory), events)
                    else:
                        with self.assertRaisesRegex(AssertionError, 'manual FLIP failed:'):
                            live.manual_flip(conn, 6, 2, Path(directory), events)
                event = live.json.loads((Path(directory) / 'flips.json').read_text())[0]
                self.assertEqual(event['wire_hex'], wire.hex())
                self.assertEqual(event['wire_repr'], repr(wire))
                self.assertEqual(event['elapsed_ns'], 335)
                self.assertEqual(event['classification'], classification)
                conn.send.assert_called_once_with('FLIP', 6, 2)  # Never retry a refusal.

    def test_timeout_preserves_partial_wire_and_diagnostic_failure(self):
        with tempfile.TemporaryDirectory(dir=live.ROOT / 'build') as directory:
            directory = Path(directory)
            (directory / 'server.log').write_bytes(b'server stderr evidence\n')
            conn = live.Conn.__new__(live.Conn)
            conn.file = mock.Mock()
            conn.file.read.return_value = b'-'
            conn.file.readline.side_effect = TimeoutError('15 second socket deadline')
            conn.send = mock.Mock()
            events = []
            with mock.patch.object(live.time, 'monotonic_ns', side_effect=[10, 15_000_000_011]):
                with self.assertRaises(TimeoutError):
                    live.manual_flip(conn, 6, 2, directory, events)
            self.assertEqual(events[0]['classification'], 'timeout')
            self.assertEqual(events[0]['wire_hex'], '2d')
            self.assertGreater(events[0]['elapsed_ns'], 15_000_000_000)
            proc = mock.Mock()
            proc.poll.return_value = None
            for failed in (False, True):
                probe = mock.Mock()
                probe.cmd.return_value = b'flip_in_progress:1\r\nflip_target_io:6\r\nio_threads:3\r\n'
                probe.cmd.side_effect = TimeoutError('INFO deadline') if failed else None
                with (mock.patch.object(live, 'Conn', return_value=probe) as connect,
                      contextlib.redirect_stderr(io.StringIO()) as stderr):
                    live.failure_receipt(self.args(directory), directory, proc, 'manual-grow',
                                         TimeoutError('original failure'), events)
                receipt = live.json.loads((directory / 'failure.json').read_text())
                self.assertIn('original failure', receipt['error'])
                self.assertEqual(receipt['server_stderr_tail'], 'server stderr evidence\n')
                self.assertIn('wire_hex', stderr.getvalue())
                if failed:
                    self.assertIn('INFO deadline', receipt['info_error'])
                else:
                    self.assertEqual(receipt['info_flip']['flip_in_progress'], '1')
                connect.assert_called_once_with('127.0.0.1', 16739, timeout=2)
                probe.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
