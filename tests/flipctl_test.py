#!/usr/bin/env python3
"""Serverless controls for GT16's stable-hold driver-stationarity classifier."""

import math
import unittest
from unittest.mock import patch

from flipctl import (PRE_HOLD_SECONDS, classify_stable_hold, rate_rule_fires,
                     stable_hold, stable_hold_attempt)


class StableHoldClassifier(unittest.TestCase):
    def classify(self, rates, moved, anchor=6000.0, band=0.0365, controller_anchor=None):
        return classify_stable_hold(rates, anchor, band, moved,
                                    anchor if controller_anchor is None else controller_anchor)

    def test_stationary_driver_with_move_fails(self):
        verdict, reason = self.classify([6000, 5997, 6002, 6001], moved=True)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("controller moved during the stable hold", reason)
        self.assertIn("driver stationary", reason)

    def test_reported_driver_dip_with_move_invalidates(self):
        # The old whole-trace mean and two-reading rule missed the reported dip.
        hold = [5977, 5847, 5697, 5774, 5866]
        self.assertEqual(rate_rule_fires([6000] * PRE_HOLD_SECONDS + hold, 0.0365), "")
        verdict, reason = self.classify(hold, moved=True)
        self.assertEqual(verdict, "INVALID")
        self.assertIn("hold sample 3", reason)
        self.assertIn("rate=5697.000/s anchor=6000.000/s", reason)
        self.assertIn("deviation=0.050500 > band=0.036500", reason)

    def test_stationary_driver_without_move_passes(self):
        verdict, reason = self.classify([6000, 5997, 6002, 6001], moved=False)
        self.assertEqual(verdict, "PASS")
        self.assertIn("no controller movement", reason)

    def test_dip_without_controller_move_is_still_invalid(self):
        for moved in (False, True):
            for second in (0, 14, 29):
                with self.subTest(moved=moved, second=second):
                    rates = [6000] * 30
                    rates[second] = 5697
                    verdict, reason = self.classify(rates, moved)
                    self.assertEqual(verdict, "INVALID")
                    self.assertIn("hold sample %d:" % (second + 1), reason)

    def test_single_second_surge_is_also_invalid(self):
        verdict, reason = self.classify([6000, 6300, 6000], moved=True)
        self.assertEqual(verdict, "INVALID")
        self.assertIn("hold sample 2", reason)

    def test_sustained_step_cannot_recenter_the_anchor(self):
        self.assertEqual(self.classify([5697] * 30, moved=True)[0], "INVALID")

    def test_band_comes_from_controller_without_a_typed_tolerance(self):
        for band, expected in ((0.02, "INVALID"), (0.04, "FAIL")):
            with self.subTest(band=band):
                self.assertEqual(self.classify([5800], moved=True, band=band)[0], expected)

    def test_band_boundary_is_inclusive_and_exceedance_is_not(self):
        self.assertEqual(self.classify([7.0, 9.0], False, anchor=8.0, band=0.125)[0], "PASS")
        for rate in (math.nextafter(7.0, 0.0), math.nextafter(9.0, math.inf)):
            with self.subTest(rate=rate):
                self.assertEqual(self.classify([rate], False, anchor=8.0, band=0.125)[0],
                                 "INVALID")

    def test_empty_window_cannot_pass(self):
        for moved in (False, True):
            with self.subTest(moved=moved):
                verdict, reason = self.classify([], moved)
                self.assertEqual(verdict, "INVALID")
                self.assertIn("no driver samples", reason)

    def test_invalid_observations_cannot_pass(self):
        for rate in (0, -1, math.nan, math.inf):
            with self.subTest(rate=rate):
                self.assertEqual(self.classify([rate], moved=False)[0], "INVALID")
        for anchor in (0, -1, math.nan, math.inf):
            with self.subTest(anchor=anchor):
                self.assertEqual(self.classify([6000], False, anchor=anchor)[0], "INVALID")
        for band in (-1, math.nan, math.inf):
            with self.subTest(band=band):
                self.assertEqual(self.classify([6000], False, band=band)[0], "INVALID")

    def test_retry_uses_fresh_driver_anchor_and_trace(self):
        self.assertEqual(self.classify([6000, 5697], moved=True)[0], "INVALID")
        self.assertEqual(self.classify([5800] * 30, False, anchor=5800)[0], "PASS")
        self.assertEqual(self.classify([5800] * 30, True, anchor=5800)[0], "FAIL")

    def test_retry_cannot_recenter_away_from_controller(self):
        self.assertEqual(self.classify([6000, 5600], True, band=0.03)[0], "INVALID")
        for moved in (False, True):
            verdict, reason = self.classify([5795] * 6, moved, anchor=5795,
                                            controller_anchor=6000, band=0.03)
            self.assertEqual(verdict, "INVALID")
            self.assertIn("controller anchor=6000.000/s", reason)
        self.assertEqual(self.classify([6000] * 6, True, anchor=6000,
                                      controller_anchor=6000, band=0.03)[0], "FAIL")

    def test_reported_retry_trace_leaves_controller_band(self):
        # Each sample fits the retry's 5795/s anchor; 5658/s is outside the
        # controller's retained 5956/s reference. The earlier arming trace also
        # leaves that band, so the live battery now rejects it before opening.
        hold = [5721, 5790, 5766, 5658, 5761, 5797]
        for rates in (hold, [5852, 5741, 5902, 5725, 5767, 5926, 5803, 5645]):
            self.assertEqual(self.classify(rates, True, anchor=5794.954,
                                          controller_anchor=5956.288, band=0.037104)[0],
                             "INVALID")

    def test_small_anchor_difference_inside_published_band_is_not_an_exemption(self):
        # 6000 -> 5795 is 3.42%, less than the incident's 3.71% band. A flat
        # trace at that rate alone does not justify excusing a controller move.
        self.assertEqual(self.classify([5795] * 6, True, anchor=5795,
                                      controller_anchor=6000, band=0.037104)[0], "FAIL")

    def test_invalid_controller_anchor_cannot_pass(self):
        for anchor in (0, -1, math.nan, math.inf):
            self.assertEqual(self.classify([6000], False, controller_anchor=anchor)[0], "INVALID")


class StableHoldSchedule(unittest.TestCase):
    """Drive the live observer with published state, including deliberately broken moves."""

    def setUp(self):
        self.now = 0.0
        self.settles = 0.0
        self.move_at = math.inf
        self.move_kind = "trigger"
        self.patches = [patch("flipctl.time.monotonic", lambda: self.now),
                        patch("flipctl.time.sleep", self.sleep),
                        patch("flipctl.info", self.info), patch("builtins.print")]
        for mock in self.patches:
            mock.start()
            self.addCleanup(mock.stop)

    def sleep(self, seconds):
        self.now += seconds

    def info(self, control, section="FLIPCTL"):
        row = dict(flipctl_state="maneuvering" if self.now < self.settles else "anchored",
                   flipctl_triggers="1", flipctl_anchor_io="6", flipctl_anchor_ex="2",
                   flipctl_rate_band="0.04", flipctl_anchor_rate="6000")
        if self.now >= self.move_at:
            if self.move_kind == "trigger":
                row["flipctl_triggers"] = "2"
            elif self.move_kind == "state":
                row["flipctl_state"] = "maneuvering"
            else:
                row["flipctl_anchor_io"], row["flipctl_anchor_ex"] = "5", "3"
        return row

    def commands(self):
        return 6000 * self.now

    def test_settling_does_not_consume_the_hold_window(self):
        self.settles = 90
        self.assertEqual(stable_hold_attempt(None, 30, 180, self.commands, [])[0], "held")
        self.assertGreaterEqual(self.now, 90 + PRE_HOLD_SECONDS + 30)

    def test_never_quiescent_cannot_pass(self):
        self.settles = math.inf
        self.assertEqual(stable_hold_attempt(None, 30, 180, self.commands, [])[0], "reroll")
        self.assertEqual(self.now, 180)

    def test_budget_cannot_shorten_the_hold(self):
        self.assertEqual(stable_hold_attempt(None, 30, 20, self.commands, [])[0], "reroll")

    def test_deliberate_movement_during_valid_hold_fails_without_retry(self):
        for self.move_kind in ("trigger", "state", "split"):
            with self.subTest(mutation=self.move_kind):
                self.now = 0
                self.move_at = PRE_HOLD_SECONDS + 2
                with self.assertRaisesRegex(AssertionError, "controller moved during"):
                    stable_hold(None, 30, self.commands, [])
                self.assertEqual(self.now, self.move_at)

    def test_more_than_three_invalid_arms_can_reach_a_full_hold(self):
        def attempt(*args):
            self.sleep(1)
            if self.now <= 4:
                return "reroll", "INVALID: injected driver excursion"
            return stable_hold_attempt(*args)
        with patch("flipctl.stable_hold_attempt", side_effect=attempt) as observer:
            self.assertEqual(stable_hold(None, 30, self.commands, [])["flipctl_triggers"], "1")
        self.assertEqual(observer.call_count, 5)
        self.assertGreaterEqual(self.now, 5 + PRE_HOLD_SECONDS + 30)

    def test_invalid_budget_exhaustion_never_passes(self):
        def attempt(*args):
            self.sleep(10)
            return "reroll", "INVALID: injected driver excursion"
        with patch("flipctl.stable_hold_attempt", side_effect=attempt):
            with self.assertRaisesRegex(AssertionError, "never opened and completed"):
                stable_hold(None, 30, self.commands, [])


if __name__ == "__main__":
    unittest.main()
