#!/usr/bin/env python3
"""Serverless controls for GT16's stable-hold driver-stationarity classifier."""

import math
import unittest

from flipctl import PRE_HOLD_SECONDS, classify_stable_hold, rate_rule_fires


class StableHoldClassifier(unittest.TestCase):
    def classify(self, rates, moved, anchor=6000.0, band=0.0365):
        return classify_stable_hold(rates, anchor, band, moved)

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


if __name__ == "__main__":
    unittest.main()
