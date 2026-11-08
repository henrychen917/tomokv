"""The selected socket must move; unrelated moves and absent windows fail."""
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
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

    def test_destination_changes_owner_during_observation_retries(self):
        # Run the real epoll_lb orchestration on a deterministic transport.
        # The destination migrates after the refused request; the accepted
        # pipeline reports its new owner. Other clients also increment moves.
        peers = []
        accepted = False
        attempts = 0
        emitted = []

        class Peer:
            def __init__(self, *args):
                self.index = len(peers)
                self.sock = SimpleNamespace(getsockname=lambda: ('127.0.0.1', 30000 + self.index))
                self.responses = []
                peers.append(self)

            def close(self):
                pass

            def must(self, *args):
                if args == ('CLIENT', 'ID'):
                    return self.index + 1
                if args == ('DEBUG', 'IO-THREAD'):
                    return 4 if accepted and self.index in (0, 64) else (0 if self.index < 64 else 1)
                assert args == ('PING',), args
                return b'PONG'

            def raw(self, data):
                nonlocal attempts, accepted
                assert self.index == 64
                self.assert_pipeline = data == (perfio.encode('DEBUG', 'CLIENT-LB', 1) +
                                               perfio.encode('DEBUG', 'IO-THREAD'))
                assert self.assert_pipeline
                attempts += 1
                accepted = attempts > 1
                self.responses = ([b'OK', 4] if accepted else [
                    perfio.RespError('ERR DEBUG CLIENT-LB client has no owner observation'), 1])

            def read(self):
                return self.responses.pop(0)

        @contextmanager
        def boot(*args):
            yield object(), SimpleNamespace(pid=123)

        def snapshot(pid):
            registered = {1000 + c.index: [44 if accepted and c.index in (0, 64)
                                           else 10 if c.index < 64 else 11] for c in peers}
            registered[999] = [10]
            return dict(stale=[], duplicates={}, registrations=97), registered

        def tcp(path):
            return 'header\n' + '\n'.join(f'0 00000000:620C 00000000:{30000+c.index:04X} 0 0 0 0 0 0 {1000+c.index}'
                                          for c in peers)

        with patch.object(perfio, 'boot', boot), patch.object(perfio, 'Conn', Peer), \
             patch.object(perfio, 'traffic'), patch.object(perfio, 'events'), \
             patch.object(perfio, 'epoll_snapshot', snapshot), \
             patch.object(perfio.Path, 'read_text', tcp), \
             patch.object(perfio.time, 'sleep'), \
             patch.object(perfio, 'emit', side_effect=lambda **row: emitted.append(row)), \
             patch.object(perfio, 'info', side_effect=[{'tomokv_clientlb_moves': '3'}, {'tomokv_clientlb_moves': '7'}]):
            perfio.epoll_lb(SimpleNamespace(port=25100))
        self.assertEqual(attempts, 2)
        destination = next(row for row in emitted if row['event'] == 'lb-destination')
        self.assertEqual((destination['destination_ep'], destination['actual_ep']), (44, [44]))
        self.assertEqual((destination['destination_io'], destination['actual_io']), (4, 4))


if __name__ == '__main__':
    unittest.main()
