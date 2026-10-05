import unittest
from fractions import Fraction as F

import nlq_limit_boundary as tool
import reference


class LimitBoundaryTests(unittest.TestCase):
    def test_integer_anchors_equal_capped_ideal_both_limits(self):
        for maximum in (1024, 1048576):
            for sample in range(1024):
                expected = reference.inverse_el(sample, dict(tool.PARAMETERS, maximum=maximum), 10, 23)
                self.assertEqual(tool.ideal_shader(sample, maximum=maximum)*65536, expected)

    def test_binding_limits_and_selected_distances(self):
        self.assertEqual(tool.cap_limit(1024), 8)
        self.assertEqual(tool.cap_limit(1048576), 8192)
        for distance, uncapped, capped in ((-2,-24,-8),(-1,-8,-8),(0,0,0),(1,8,8),(2,24,8)):
            self.assertEqual(tool.ideal_shader(512+distance)*65536, uncapped)
            self.assertEqual(tool.ideal_shader(512+distance, maximum=1024)*65536, capped)
        self.assertEqual(tool.ideal_shader(0)*65536, -8184)
        self.assertEqual(tool.ideal_shader(1023)*65536, 8168)

    def test_fractional_raw_boundaries_and_signed_floor(self):
        self.assertEqual(tool.ideal_shader(F(32767,64))*65536, F(31,4))
        self.assertEqual(tool.ideal_shader(F(32769,64))*65536, F(-31,4))
        self.assertEqual(tool.evaluate(F(32767,64))["hypothetical_capped_floor"], 7)
        self.assertEqual(tool.evaluate(F(32769,64))["hypothetical_capped_floor"], -8)
        for s in (F(511*64-1,64), F(513*64+1,64)):
            self.assertEqual(abs(tool.ideal_shader(s, maximum=1024)*65536), 8)
            self.assertIsNone(tool.evaluate(s)["unchanged_integer_reference"])

    def test_exact_guard_boundaries(self):
        lower = F(1,8192)
        upper = F(512,(1<<22)-1)
        for sample in (512,512-lower,512+upper):
            self.assertEqual(tool.ideal_shader(sample), 0)
        self.assertNotEqual(tool.ideal_shader(512-lower-F(1,1<<40)), 0)
        self.assertNotEqual(tool.ideal_shader(512+upper+F(1,1<<40)), 0)

    def test_secondary_cap_before_floor_signed_asymmetry(self):
        self.assertEqual(tool.cap_limit(1025), F(1025,128))
        for sample, expected in ((510,-9),(514,8)):
            row = tool.evaluate(sample,1025)
            self.assertEqual(row["unchanged_integer_reference"], expected)
            self.assertEqual(row["hypothetical_capped_floor"], expected)
        self.assertEqual(tool.report()["secondary_clamp_before_floor_control"]["maximum"],1025)

    def test_reject_inexact_or_outside_inputs(self):
        for value in (True,512.0,-1,1024,"512"):
            with self.assertRaises(ValueError): tool.ideal_shader(value)
        for maximum in (True,1.0,-1,1<<25):
            with self.assertRaises(ValueError): tool.cap_limit(maximum)

    def test_report_counts_hashes_and_compact_selected_rows(self):
        report = tool.report()
        self.assertEqual(report, tool.report())
        for maximum, fixture in report["fixtures"].items():
            anchors = fixture["integer_anchors"]
            self.assertEqual(anchors["samples"], 1024)
            self.assertEqual(anchors["integer_reference_minus_capped_ideal_histogram"], [{"value":[0,1],"count":1024}])
            self.assertEqual(fixture["near_neutral_raw_word_sweep"]["samples"], 385)
            self.assertEqual(len(fixture["selected_rows"]),9)
            for scope in (anchors, fixture["near_neutral_raw_word_sweep"]):
                for field in ("cap_difference_histogram", "hypothetical_floor_difference_histogram"):
                    self.assertEqual(sum(v["count"] for v in scope[field]), scope["samples"])
            self.assertEqual(anchors["cap_changed_samples"], 1021 if maximum == "1024" else 0)


if __name__ == "__main__": unittest.main()
