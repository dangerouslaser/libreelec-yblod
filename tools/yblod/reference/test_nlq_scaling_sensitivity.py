from fractions import Fraction as F
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import nlq_scaling_sensitivity as n
import reference


class SensitivityTests(unittest.TestCase):
    def test_exhaustive_integer_2296_contract(self):
        for sample in range(1024):
            self.assertEqual(n.floor_extension(sample), reference.inverse_el(sample, n.PARAMETERS, 10, 23))
            distance = sample - 512
            literal = 16 * distance - 8 * ((distance > 0) - (distance < 0))
            self.assertEqual(n.formula_extension(sample), literal)

    def test_generic_depth_threshold_bound_and_floor(self):
        for depth in (8, 10):
            for parameters in ({"offset": 1 << (depth - 1), "slope": 3, "threshold": 1, "maximum": 17},
                               {"offset": 0, "slope": 512, "threshold": 256, "maximum": 7}):
                for sample in range(1 << depth):
                    self.assertEqual(n.floor_extension(sample, parameters, depth, 20),
                                     reference.inverse_el(sample, parameters, depth, 20))
        self.assertEqual(n.floor_extension(511, {"offset": 512, "slope": 3, "threshold": 0, "maximum": 100}, 10, 20), -1)

    def test_raw_low_bits_retained(self):
        score = n.score_pair(524 * 64 + 1, 524)
        self.assertEqual(score["sample_error_native_codes"], [1, 64])
        self.assertEqual(score["extension_residual_error_16bit_units"], [1, 4])
        self.assertEqual(score["extension_error_unrounded_12bit_units"], [1, 64])
        self.assertIsNone(score["integer_reference_actual"])

    def test_small_same_branch_errors(self):
        for anchor in (500, 524):
            for delta in (F(-1, 2), F(1, 2), F(-1, 4), F(1, 4)):
                score = n.score_pair(int((anchor + delta) * 64), anchor)
                self.assertEqual(F(*score["extension_residual_error_16bit_units"]), delta * 16)

    def test_neutral_fractional_behavior_is_not_hidden(self):
        self.assertEqual(n.formula_extension(512), 0)
        self.assertEqual(n.formula_extension(F(2049, 4)), -4)
        self.assertEqual(n.formula_extension(F(2047, 4)), 4)
        self.assertEqual(n.formula_extension(F(32769, 64)), F(-31, 4))
        self.assertEqual(n.formula_extension(F(1025, 2)), 0)
        score = n.score_pair(512 * 64 + 16, F(2047, 4))
        self.assertEqual(score["sample_error_native_codes"], [1, 2])
        self.assertEqual(score["extension_residual_error_16bit_units"], [-8, 1])
        self.assertEqual(score["neutral_relation"], {"expected": -1, "actual": 1})
        self.assertIsNone(score["normative_fractional_result"])

    def test_final_rounding_and_bounds(self):
        self.assertEqual(n.reconstruct_extension(32768, F(31, 4)), 2048)
        self.assertEqual(n.reconstruct_extension(32768, 8), 2049)
        self.assertEqual(n.reconstruct_extension(0, -100), 0)
        self.assertEqual(n.reconstruct_extension(65535, 100), 4095)
        for numerator in range(-130, 130):
            residual = F(numerator, 4)
            self.assertEqual(n.reconstruct_extension(32768, residual),
                             reference.reconstruct(32768, residual.numerator // residual.denominator, 12))

    def test_reject_implicit_precision_or_range_policy(self):
        for sample in (True, 512.0, -1, 1024):
            with self.assertRaises(ValueError): n.formula_extension(sample)
        for word in (False, 32768.0, -1, 65536, 65535):
            with self.assertRaises(ValueError): n.score_pair(word, 512)
        for parameters in ({}, dict(n.PARAMETERS, slope=-1), dict(n.PARAMETERS, offset=1024),
                           dict(n.PARAMETERS, extra=0), dict(n.PARAMETERS, slope=True)):
            with self.assertRaises(ValueError): n.formula_extension(512, parameters)
        with self.assertRaises(ValueError): n.formula_extension(512, bit_depth=9)
        with self.assertRaises(ValueError): n.formula_extension(512, denominator=14)
        with self.assertRaises(ValueError): n.score_pair(32768, 512.0)

    def test_report_and_no_overwrite(self):
        value = n.report()
        self.assertEqual(len(value["cases"]), 30)
        self.assertIn("unknown", value["normative_fractional_behavior"])
        self.assertEqual({c["component"] for c in value["cases"]}, {"Y", "Cb", "Cr"})
        for component in ("Y", "Cb", "Cr"):
            summary = value["synthetic_composition_summary"][component]
            self.assertEqual(summary["synthetic_pairs"], 50)
            self.assertGreater(summary["actual_clipped_count"], 0)
            self.assertGreater(summary["expected_clipped_count"], 0)
            self.assertGreater(summary["unclipped_pair_count"], 0)
        for case in value["cases"]:
            interior = case["synthetic_composition_sweep"][2]
            self.assertFalse(interior["actual"]["clipped"])
            self.assertFalse(interior["expected"]["clipped"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sensitivity.json"
            command = [sys.executable, n.__file__, str(output)]
            done = subprocess.run(command, capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            original = output.read_bytes()
            self.assertEqual(json.loads(original)["schema"], value["schema"])
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
