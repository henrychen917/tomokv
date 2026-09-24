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
        proc.poll.side_effect = [0, 0] if boot_failed else [None, 0]
        conn = mock.Mock()
        conn.cmd.side_effect = lambda *v: b'PONG' if v == ('PING',) else b'OK'
        with (mock.patch.object(live.subprocess, 'Popen', return_value=proc) as spawn,
              mock.patch.object(live, 'Conn', return_value=conn),
              mock.patch.object(live, 'productive') as productive,
              mock.patch.object(live, 'wait_parked', return_value={'112': 'io_uring'}),
              mock.patch.object(live, 'load_report', return_value=report)):
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


if __name__ == '__main__':
    unittest.main()
