#!/usr/bin/env python3
"""Serverless controls for the live framing schedule; a missing witness must be red."""
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import patch

import aof_frame_order as battery


class Clock:
    now = 0.0

    def monotonic(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Schedule:
    def __init__(self, directory, *, pause=True, group=True, large=True, fired=True,
                 group_reply=2, write_reply=b"OK"):
        self.marker = Path(directory) / "debug-aof-rewrite-stage"
        self.state = Path(directory) / "debug-aof-frame-state"
        self.pause, self.group, self.large, self.fired = pause, group, large, fired
        self.group_reply, self.write_reply = group_reply, write_reply
        self.pending, self.posted = 0, 100
        self.released = False
        self.commands = []

    def cmd(self, *args):
        self.commands.append(args[:3])
        if args == ("INFO", "Persistence"):
            values = {"aof_rewrites": int(self.released),
                      "aof_groups_committed": int(self.released),
                      "aof_control_frames_deferred": int(self.released and self.fired)}
            return "\r\n".join("%s:%d" % row for row in values.items()).encode()
        if args == ("DEBUG", "AOF-REWRITE-PAUSE", "after-manifest"):
            return b"OK"
        if args == ("BGREWRITEAOF",):
            if self.pause:
                self.state.write_text("5 0 100\n")
                self.marker.write_text("after-manifest\n")
            return b"Background append only file rewriting started"
        if args == ("DEBUG", "AOF-REWRITE-PAUSE", "off"):
            self.released, self.pending = True, 0
            self.state.unlink(missing_ok=True)
            return b"OK"
        if args[0] == "EVAL":
            if self.group:
                self.pending, self.posted = 3, 103
                self.state.write_text("5 3 103\n")
            return self.group_reply
        if args[0] == "GET":
            return b"directed-window-l"
        if args[0] == "STRLEN":
            return battery.LARGE_BYTES
        raise AssertionError("unexpected command %r" % (args,))

    def send(self, *args):
        self.commands.append(args[:2])
        if self.large:
            self.pending, self.posted = 4, 104
            self.state.write_text("5 4 104\n")

    def read(self):
        if not self.released:
            raise AssertionError("large SET was read before writer release")
        return self.write_reply


class FramingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        clock = Clock()
        self.enterContext(patch.object(battery.time, "monotonic", clock.monotonic))
        self.enterContext(patch.object(battery.time, "sleep", clock.sleep))
        self.enterContext(patch.object(battery, "DEADLINE_S", 0.5))
        self.enterContext(patch.object(battery.socket, "create_connection",
                                       side_effect=AssertionError("unit opened a socket")))

    def run_schedule(self, **options):
        schedule = Schedule(self.directory, **options)
        return schedule, lambda: battery.directed_window(
            schedule, schedule, ["low", "high"], self.directory, 5)

    def test_success_requires_every_witness_and_releases_before_read(self):
        schedule, run = self.run_schedule()
        fired, groups, _ = run()
        self.assertEqual((fired, groups), (1, 1))
        self.assertTrue(schedule.released)
        self.assertFalse(schedule.marker.exists())
        verbs = [row[0] for row in schedule.commands]
        self.assertLess(verbs.index("EVAL"), verbs.index("SET"))
        self.assertEqual(sum(row[0] == "EVAL" for row in schedule.commands), 1)

    def test_each_absent_arming_witness_fails_and_disarms(self):
        for option, message in (("pause", "writer pause"), ("group", "group fragments"),
                                ("large", "LargeBegin")):
            with self.subTest(option=option):
                schedule, run = self.run_schedule(**{option: False})
                with self.assertRaisesRegex(AssertionError, message):
                    run()
                self.assertTrue(schedule.released)
                self.assertFalse(schedule.marker.exists())

    def test_no_deferral_cannot_pass_despite_clean_completion(self):
        _, run = self.run_schedule(fired=False)
        with self.assertRaisesRegex(AssertionError, "never held"):
            run()

    def test_bad_replies_fail_without_rearming(self):
        for options, message in (({"group_reply": 1}, "group did not return"),
                                 ({"write_reply": b"NO"}, "large SET did not complete")):
            with self.subTest(options=options):
                schedule, run = self.run_schedule(**options)
                with self.assertRaisesRegex(AssertionError, message):
                    run()
                self.assertEqual(sum(row[0] == "EVAL" for row in schedule.commands), 1)
                self.assertTrue(schedule.released)

    def test_frame_state_rejects_missing_and_malformed_fields(self):
        self.assertIsNone(battery.frame_state(self.directory))
        for state in ("", "5 0", "5 0 extra", "5 -1 1", "5 True 1", "5 0 1 2"):
            with self.subTest(state=state):
                (Path(self.directory) / "debug-aof-frame-state").write_text(state)
                with self.assertRaisesRegex(AssertionError, "invalid debug-aof-frame-state"):
                    battery.frame_state(self.directory)
        (Path(self.directory) / "debug-aof-frame-state").write_text("5 4 104\n")
        self.assertEqual(battery.frame_state(self.directory), [5, 4, 104])

    def test_pair_uses_actual_owner_order_and_excludes_writer(self):
        with patch.object(battery._lib, "shards_of", return_value=[(0, 7), (1, 5), (2, 6)]):
            self.assertEqual(battery.ordered_pair(None, ["high", "writer", "low"], 5),
                             ["low", "high"])
        with patch.object(battery._lib, "shards_of", return_value=[(0, 6), (1, 6)]):
            with self.assertRaisesRegex(AssertionError, "two shard owners"):
                battery.ordered_pair(None, ["a", "b"], 5)

    def test_stale_marker_is_not_a_successful_arm(self):
        schedule, run = self.run_schedule()
        schedule.marker.write_text("after-manifest\n")
        with self.assertRaisesRegex(AssertionError, "stale AOF rewrite marker"):
            run()
        self.assertEqual(schedule.commands, [])

    def test_control_avoids_writer_and_full_channel_producer(self):
        created = []
        class Client:
            def __init__(self, *args):
                self.tid = [5, 7, 2][len(created)]
                self.closed = False
                created.append(self)
            def cmd(self, *args):
                return self.tid
            def close(self):
                self.closed = True
        with patch.object(battery, "Resp", Client):
            chosen = battery.usable_connection("unused", 0, {5, 7})
        self.assertEqual(chosen.tid, 2)
        self.assertEqual([client.closed for client in created], [True, True, False])

    def test_failed_unlink_still_disarms_and_preserves_original_failure(self):
        schedule, _ = self.run_schedule()
        with patch.object(Path, "unlink", side_effect=OSError("unlink failure")):
            with self.assertRaisesRegex(OSError, "unlink failure"):
                battery.release_pause(schedule, schedule.marker)
            self.assertTrue(schedule.released)
            with patch.object(battery.sys, "stderr", io.StringIO()):
                with self.assertRaisesRegex(AssertionError, "original witness failure"):
                    try:
                        raise AssertionError("original witness failure")
                    finally:
                        battery.release_pause(schedule, schedule.marker)


if __name__ == "__main__":
    unittest.main()
