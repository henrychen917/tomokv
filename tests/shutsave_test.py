#!/usr/bin/env python3
"""Serverless controls for the live proof's arming and exact PRE fatal checks."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import shutsave


class ShutdownWitness(unittest.TestCase):
    def setUp(self):
        build = Path(__file__).resolve().parents[1] / 'build'
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=build)))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def fixture(self, fatal='', status=1, partial=True):
        directory = self.root / 'attempt'
        directory.mkdir()
        (directory / 'dump.tomo').write_bytes(b'baseline')
        log = directory / 'write.log'
        log.write_text(fatal)
        if partial:
            with (directory / 'dump.tomo.tmp.1.2').open('wb') as file:
                file.truncate(65536)
        conn, peer, process = Mock(), Mock(), Mock()
        conn.must.return_value = b'OK'
        conn.read.return_value = b'OK'
        process.poll.return_value = None
        process.wait.return_value = status
        @contextlib.contextmanager
        def boot(*args):
            yield process, conn, log
        args = SimpleNamespace(operation='SAVE', action='sigterm', keys=64,
                               expect_pre_fatal=True)
        self.enterContext(patch.object(shutsave, 'boot', boot))
        self.enterContext(patch.object(shutsave, 'seed_save_load'))
        self.enterContext(patch.object(shutsave, 'stop_peer', return_value=peer))
        self.enterContext(patch.object(shutsave.select, 'select', return_value=([conn.sock], [], [])))
        return args, directory, process

    def test_completed_save_without_a_partial_window_is_not_a_pass(self):
        args, directory, process = self.fixture(partial=False)
        self.assertIsNone(shutsave.attempt(args, directory))
        process.send_signal.assert_not_called()
        process.wait.assert_not_called()

    def test_pre_requires_the_specific_worker_shutdown_fatal(self):
        args, directory, process = self.fixture('fatal: unrelated boot failure')
        with self.assertRaises(AssertionError):
            shutsave.attempt(args, directory)
        self.assertLessEqual(process.wait.call_args.kwargs['timeout'], 10)

    def test_exact_pre_fatal_with_a_written_prefix_is_accepted(self):
        args, directory, process = self.fixture('fatal: database worker shutdown timeout elapsed_ms=2703')
        result = shutsave.attempt(args, directory)
        self.assertEqual(result['status'], 1)
        self.assertEqual(result['witness']['bytes'], 65536)
        process.send_signal.assert_called_once()

    def test_clean_pre_exit_does_not_prove_the_old_bug(self):
        args, directory, _ = self.fixture('fatal: database worker shutdown timeout', status=0)
        with self.assertRaises(AssertionError):
            shutsave.attempt(args, directory)

    def test_missing_window_rearms_on_three_distinct_fresh_directories_then_fails(self):
        root = self.root / 'proof'
        with patch.object(sys, 'argv', ['shutsave.py', '--binary', '/unused', '--root', str(root),
                                       '--action', 'sigterm']), \
                patch.object(shutsave, 'attempt', return_value=None) as attempt, \
                self.assertRaisesRegex(AssertionError, 'never armed in three fresh datasets'):
            shutsave.main()
        directories = [call.args[1] for call in attempt.call_args_list]
        self.assertEqual(len(directories), 3)
        self.assertEqual(len(set(directories)), 3)
        self.assertTrue(all(path.is_dir() for path in directories))


if __name__ == '__main__':
    unittest.main()
