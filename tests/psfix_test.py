#!/usr/bin/env python3
"""Serverless controls for the directed background-save overlap proof."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import psfix
from _save_timeout import save_reply_timeout, save_timeout_seconds


class SaveLoadProof(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / 'build'
        scratch.mkdir(exist_ok=True)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            dir=scratch)))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.peers = [Mock(), Mock()]
        for peer in self.peers:
            peer.must.return_value = b'Background saving started'
        self.sleep = self.enterContext(patch.object(psfix.time, 'sleep'))

    def result(self, stdout='', returncode=0):
        return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)

    def test_requires_two_live_jobs_and_the_real_before_save_wait(self):
        output = 'PSFIX idle barrier before target SAVE: polls=102 busy_peers=target,oracle\n'
        with patch.object(psfix, 'info', side_effect=[{'rdb_bgsave_in_progress': state}
                                                     for state in ('0', '0', '1', '1')]), \
                patch.object(psfix.subprocess, 'run', return_value=self.result(output)) as run:
            self.assertEqual(psfix.run_differ(['differ'], self.root / 'leg.log', self.peers), (0, output))
        run.assert_called_once()
        self.sleep.assert_called_once_with(.101)
        self.assertEqual((self.root / 'leg.log').read_text(), output)

    def test_short_save_never_starts_a_vacuous_leg(self):
        with patch.object(psfix, 'info', side_effect=[{'rdb_bgsave_in_progress': state}
                                                     for state in ('0', '0', '1', '0')]), \
                patch.object(psfix.subprocess, 'run') as run, \
                self.assertRaisesRegex(AssertionError, 'never armed for >100 ms on oracle'):
            psfix.run_differ(['differ'], self.root / 'leg.log', self.peers)
        run.assert_not_called()

    def test_missing_or_one_peer_barrier_is_not_a_proof(self):
        for output in ('DIFFER psfix: PASS',
                       'PSFIX idle barrier before target SAVE: polls=2 busy_peers=target',
                       'PSFIX idle barrier after target BGSAVE: polls=2 busy_peers=target,oracle'):
            with self.subTest(output=output), \
                    patch.object(psfix, 'info', side_effect=[{'rdb_bgsave_in_progress': state}
                                                           for state in ('0', '0', '1', '1')]), \
                    patch.object(psfix.subprocess, 'run', return_value=self.result(output)), \
                    self.assertRaisesRegex(AssertionError, 'did not overlap.*BOTH peers'):
                psfix.run_differ(['differ'], self.root / 'leg.log', self.peers)

    def test_load_off_preserves_plain_differential_failures(self):
        with patch.object(psfix, 'info') as info, \
                patch.object(psfix.subprocess, 'run', return_value=self.result('failure', 1)):
            self.assertEqual(psfix.run_differ(['differ'], self.root / 'leg.log', []), (1, 'failure'))
        info.assert_not_called()
        self.sleep.assert_not_called()

    def test_large_save_budgets_cover_four_saves_and_restore_on_error(self):
        size = 512 * 1024 * 1024
        self.assertEqual(save_timeout_seconds(0), 30)
        self.assertEqual(save_timeout_seconds(size), 94)
        self.assertEqual(save_timeout_seconds(2 * size), 158)
        sock = Mock()
        sock.gettimeout.return_value = 30
        with self.assertRaises(TimeoutError):
            with save_reply_timeout(sock, size):
                sock.settimeout.assert_called_with(94)
                raise TimeoutError('injected slow save')
        sock.settimeout.assert_called_with(30)
        with patch.object(psfix.subprocess, 'run', return_value=self.result()) as run:
            psfix.run_differ(['differ'], self.root / 'large.log', [], size)
        self.assertGreaterEqual(run.call_args.kwargs['timeout'], 4 * 94 + 12 * 10)

    def test_process_budget_includes_larger_peers_memory_overhead(self):
        output = 'PSFIX idle barrier before target SAVE: polls=102 busy_peers=target,oracle\n'
        replies = [{'used_memory': str(768 * 1024 * 1024)}, {'used_memory': str(512 * 1024 * 1024)}]
        replies += [{'rdb_bgsave_in_progress': state} for state in ('0', '0', '1', '1')]
        with patch.object(psfix, 'info', side_effect=replies), \
                patch.object(psfix.subprocess, 'run', return_value=self.result(output)) as run:
            psfix.run_differ(['differ'], self.root / 'memory.log', self.peers, 512 * 1024 * 1024)
        self.assertGreaterEqual(run.call_args.kwargs['timeout'], 4 * 126 + 12 * 10)

    def test_existing_long_timeout_is_preserved_and_bad_size_rejected(self):
        sock = Mock()
        sock.gettimeout.return_value = 200
        with save_reply_timeout(sock, 512 * 1024 * 1024):
            sock.settimeout.assert_called_with(200)
        sock.settimeout.assert_called_with(200)
        with self.assertRaises(ValueError):
            save_timeout_seconds(-1)


if __name__ == '__main__':
    unittest.main()
