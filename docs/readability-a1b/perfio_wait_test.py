"""The selected socket must move; unrelated moves and absent windows fail."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
import perfio


class SelectedMove(unittest.TestCase):
    def wait(self, registrations, times):
        with patch.object(perfio, 'epoll_snapshot', side_effect=[({}, r) for r in registrations]) as snapshot, \
             patch.object(perfio.time, 'monotonic', side_effect=times), \
             patch.object(perfio.time, 'sleep'):
            perfio.wait_epoll_move(123, 100, 28, 35)
            return snapshot.call_count

    def test_other_client_moves_first(self):
        self.assertEqual(self.wait([{100: [27], 200: [28]}, {100: [28], 200: [28]}], [1]), 2)

    def test_unrelated_move_cannot_satisfy_deadline(self):
        with self.assertRaisesRegex(AssertionError, 'selected client-LB move never completed'):
            self.wait([{100: [27], 200: [28]}], [35])

    def test_duplicate_destination_is_not_completion(self):
        with self.assertRaises(AssertionError):
            self.wait([{100: [27, 28]}], [35])

    def test_missing_registration_is_not_completion(self):
        with self.assertRaises(AssertionError):
            self.wait([{}], [35])


if __name__ == '__main__':
    unittest.main()
