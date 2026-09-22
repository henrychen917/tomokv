#!/usr/bin/env python3
"""Serverless argv and boot-diagnostic controls; no child or socket is opened."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mdbqsbr_live as live


def pre_fix_command(binary, args):
    """Frozen command expression from boot() at 1acfe491a: the negative control."""
    return ['taskset', '-c', args.cores, str(binary), '--bind', '127.0.0.1',
            '--port', str(args.port), '--thread-mode', args.mode,
            '--shards', '16', '--ratio', '6:2', '--databases', '16',
            '--read-local', str(args.read_local), '--atomic', str(args.atomic),
            '--enable-debug-command', 'yes', '--save', '', '--protected-mode', 'no']


def arguments(mode='1s', read_local=0, atomic=0, **extra):
    return SimpleNamespace(mode=mode, read_local=read_local, atomic=atomic,
                           cores='112-119', port=7900, **extra)


class LiveHarnessTests(unittest.TestCase):
    def setUp(self):
        # Any path this unit forgot to mock fails instead of launching/connecting.
        self.popen = self.enterContext(patch.object(
            live.subprocess, 'Popen', side_effect=AssertionError('unexpected child launch')))
        self.conn = self.enterContext(patch.object(
            live, 'Conn', side_effect=AssertionError('unexpected connection')))
        (live.ROOT / 'build').mkdir(exist_ok=True)
        self.output = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix='mdbqsbr-live-unit-', dir=live.ROOT / 'build')))

    def assert_fused_argv(self, command):
        self.assertNotIn('--ratio', command, '1s argv contains split-only --ratio')
        # validate_config also rejects flip_auto=1 in fused; the harness leaves
        # that knob at its valid default 0, just like gate boot_fused.
        self.assertNotIn('--flip-auto', command)

    def test_mode_matrix_preserves_split_and_other_flags(self):
        for mode in ('1s', '2s'):
            for read_local in (0, 1):
                for atomic in (0, 1):
                    with self.subTest(mode=mode, read_local=read_local, atomic=atomic):
                        args = arguments(mode, read_local, atomic)
                        command = live.build_command(Path('/unused/tomokv'), args)
                        expected = pre_fix_command(Path('/unused/tomokv'), args)
                        if mode == '1s':
                            self.assert_fused_argv(command)
                            ratio = expected.index('--ratio')
                            del expected[ratio:ratio + 2]
                        else:
                            self.assertEqual(command[command.index('--ratio') + 1], '6:2')
                        self.assertEqual(command, expected)

    def test_pre_fix_fused_builder_fails_same_assertion(self):
        for read_local in (0, 1):
            for atomic in (0, 1):
                with self.subTest(read_local=read_local, atomic=atomic):
                    command = pre_fix_command('/unused/tomokv',
                                              arguments('1s', read_local, atomic))
                    with self.assertRaisesRegex(AssertionError,
                                                '1s argv contains split-only --ratio'):
                        self.assert_fused_argv(command)

    def test_boot_launches_and_records_the_builder_argv(self):
        self.popen.side_effect = None
        for mode in ('1s', '2s'):
            with self.subTest(mode=mode), (self.output / 'server.log').open('wb') as log:
                args = arguments(mode)
                binary = Path('/unused/tomokv')
                self.assertIs(live.boot(binary, args, self.output, log), self.popen.return_value)
                command = live.build_command(binary, args)
                self.assertEqual(self.popen.call_args.args, (command,))
                self.assertEqual(json.loads((self.output / 'command.json').read_text()), command)
                self.assertIs(self.popen.call_args.kwargs['stdout'], log)
                self.assertEqual(self.popen.call_args.kwargs['stderr'], live.subprocess.STDOUT)

    def launch_fixture(self, returncode, diagnostic):
        proc = Mock(pid=41001)
        proc.poll.return_value = returncode
        proc.wait.return_value = returncode

        def launch(command, **kwargs):
            kwargs['stdout'].write(('old log line\n' * 30 + diagnostic + '\n').encode())
            return proc

        self.popen.side_effect = launch
        return proc

    def assert_boot_receipt(self, arm, message):
        result = json.loads((self.output / f'idle-{arm}-0/result.json').read_text())
        self.assertEqual(result['failure_phase'], 'boot')
        self.assertEqual(result['error'], message)
        self.assertNotIn('expected_timeout', result)
        self.assertNotIn('reply_seconds', result)

    def test_exited_child_reports_log_tail_in_every_arm(self):
        diagnostic = ('--ratio is unavailable with --thread-mode 1s: '
                      'every thread handles networking and execution')
        for arm in ('production', 'parked', 'no-wake'):
            with self.subTest(arm=arm):
                proc = self.launch_fixture(1, diagnostic)
                with self.assertRaises(live.BootFailure) as caught:
                    live.run_case('/unused/tomokv', arguments(output=self.output),
                                  'idle', arm, 0)
                message = str(caught.exception)
                self.assertIn('server boot failed (pid=41001, exit=1)', message)
                self.assertIn(diagnostic, message)
                self.assertEqual(message.count('old log line'), 24)
                self.assertIn('server.log (stdout/stderr):', message)
                self.assertNotIn('SWAPDB', message)
                self.assert_boot_receipt(arm, message)
                self.conn.assert_not_called()
                proc.kill.assert_not_called()
                proc.wait.assert_called_once_with(timeout=live.SHUTDOWN)

    def test_readiness_deadline_reports_log_and_reaps_child(self):
        proc = self.launch_fixture(None, 'listener never became ready')
        self.conn.side_effect = ConnectionRefusedError('not listening')
        with patch.object(live.time, 'monotonic',
                          side_effect=[0, 0, live.WORKERS * live.SHUTDOWN]), \
                patch.object(live.time, 'sleep'), self.assertRaises(live.BootFailure) as caught:
            live.run_case('/unused/tomokv', arguments(output=self.output), 'idle', 'no-wake', 0)
        message = str(caught.exception)
        self.assertIn('boot deadline expired', message)
        self.assertIn('listener never became ready', message)
        self.assert_boot_receipt('no-wake', message)
        self.conn.assert_called_once()
        proc.kill.assert_called_once()
        proc.wait.assert_called_once_with(timeout=live.SHUTDOWN)

    def test_launch_error_stays_a_boot_failure_with_empty_log(self):
        self.popen.side_effect = FileNotFoundError('missing executable')
        with self.assertRaises(live.BootFailure) as caught:
            live.run_case('/unused/tomokv', arguments(output=self.output), 'idle', 'no-wake', 0)
        message = str(caught.exception)
        self.assertIn('server boot failed (not started): missing executable', message)
        self.assertIn('(empty log)', message)
        self.assert_boot_receipt('no-wake', message)
        self.conn.assert_not_called()

    def test_disconnect_timeout_is_a_failure_before_shutdown(self):
        with patch.object(live.subprocess, 'run', side_effect=subprocess.TimeoutExpired('serial', 1)), \
                self.assertRaisesRegex(AssertionError, 'disconnect serial battery timed out before shutdown'):
            live.disconnects(Mock(), arguments(), self.output)

    def test_disconnect_failure_is_not_a_wake_control_success(self):
        with patch.object(live.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), \
                self.assertRaisesRegex(AssertionError, 'disconnect serial battery failed'):
            live.disconnects(Mock(), arguments(), self.output)

    def test_disconnect_success_requires_actual_client_drain(self):
        admin = Mock()
        admin.cmd.return_value = b'PONG'
        with patch.object(live.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch.object(live, 'info', side_effect=[{'connected_clients': '2'},
                                                      {'connected_clients': '1'}]) as info, \
                patch.object(live.time, 'sleep'):
            live.disconnects(admin, arguments(), self.output)
        self.assertEqual(info.call_count, 2)
        admin.cmd.assert_called_once_with('PING')
        self.assertEqual(run.call_args.kwargs['timeout'], live.WORKERS * live.SHUTDOWN)

    def test_undrained_clients_fail_instead_of_skipping(self):
        with patch.object(live.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                patch.object(live, 'info', return_value={'connected_clients': '2'}), \
                patch.object(live.time, 'monotonic', side_effect=[0, live.SHUTDOWN]), \
                self.assertRaisesRegex(AssertionError, 'disconnected clients never passed their lifetime fence'):
            live.disconnects(Mock(), arguments(), self.output)


if __name__ == '__main__':
    unittest.main()
