from fractions import Fraction as F
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import nlq_scaling_sensitivity as n
import reference
import y416_large_geometry as geometry


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

    def measured_fixture(self):
        value = {"schema": "yblod.hardware-y416-large.v1", "status": "complete",
                 "all_sameformat_p010_gates_complete": True, "repeats": 2,
                 "binary_sha256": "a" * 64, "source_sha256": "b" * 64,
                 "inputs": {}, "results": {"native": {}, "scaled": {}}}
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                case = f"{component}-{axis}-ascending"
                extent = geometry.COMPONENT_SIZES[component][0 if axis == "x" else 1]
                start = extent // 2 - 48
                value["inputs"][case] = {"sha256": "c" * 64, "case_spec": {
                    "component": component, "axis": axis, "signed_slope": 8,
                    "baseline_code": 512, "native_band_length": 96,
                    "band_start_native": start, "band_stop_native_exclusive": start + 96,
                    "source_center_native_index": start + 48, "band_first_code": 128,
                    "band_last_code": 888, "native_component_sizes": geometry.COMPONENT_SIZES,
                    "input_size": geometry.INPUT}}
                for label, size in (("native", [1920, 1080]), ("scaled", [3840, 2160])):
                    length = size[0 if axis == "x" else 1]
                    raw = []
                    for index in range(length):
                        # Independently construct the centre convention, not by
                        # calling the production geometry coordinate helper.
                        position = (F(index) + F(1, 2)) / (2 if label == "scaled" else 1) - F(1, 2)
                        if component != "Y":
                            position = (position - (F(1, 2) if axis == "y" else 0)) / 2
                        expected = 128 + 8 * (min(start + 95, max(start, position)) - start)
                        raw.append(int((expected + F(1, 4)) * 64))
                    value["results"][label][case] = {
                        "size": size, "bytes": size[0] * size[1] * 8,
                        "repeat_stable": True, "sha256": "d" * 64, "repeat_sha256": ["d" * 64] * 2,
                        "profile_sampling": {"center_row_y": size[1] // 2, "center_column_x": size[0] // 2},
                        "UYVA_word_indices_hypothesis": {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3},
                        "raw_le16_word_positions": {geometry.WORDS[component]: {
                            "center_row_raw_words" if axis == "x" else "center_column_raw_words": raw}}}
        return value

    def test_measured_pairs_exact_and_bounded(self):
        result = n.analyse_measured(self.measured_fixture())
        self.assertEqual(result["total_samples"], 1536)
        for case, row in result["cases"].items():
            count = 128 if case.startswith("Y-") else 320
            self.assertEqual(row["samples"], count)
            self.assertEqual(row["sample_error_native_codes_histogram"], [{"value": [1, 4], "count": count}])
            self.assertEqual(row["extension_residual_error_16bit_histogram"], [{"value": [4, 1], "count": count}])
            self.assertEqual(row["synthetic_composition_clipped_counts"], {"actual": 0, "expected": 0})
            self.assertEqual(row["opposite_nonzero_sign_count"], 0)
            self.assertLessEqual(len(row["first_examples"]), 3)
            self.assertLessEqual(len(row["near_neutral_or_crossing_examples"]), 6)

    def test_measured_crossing_keeps_raw_fraction(self):
        value = self.measured_fixture()
        sample = value["results"]["scaled"]["Cb-x-ascending"]
        raw = sample["raw_le16_word_positions"]["0"]["center_row_raw_words"]
        # Source centre is480. At output1920, expected511, while this
        # explicitly perturbed fixture reads512.25: a sign crossing.
        raw[1920] = 32784
        row = n.analyse_measured(value)["cases"]["Cb-x-ascending"]
        self.assertEqual(row["opposite_nonzero_sign_count"], 1)
        self.assertEqual(row["neutral_distance_native_codes"]["actual"]["within_half_code_inclusive_count"], 1)
        pair = row["near_neutral_or_crossing_examples"][0]
        self.assertEqual(pair["expected_native_codes"], [511, 1])
        self.assertEqual(pair["sample_native_codes"], [2049, 4])
        self.assertEqual(pair["extension_residual_error_16bit_units"], [4, 1])

    def test_measured_invalid_declarations(self):
        original = self.measured_fixture()
        for mutation in ("gate", "repeat", "repeat_hash", "mapping", "mapping_false", "raw", "source", "profile"):
            value = copy.deepcopy(original)
            sample = value["results"]["scaled"]["Y-x-ascending"]
            if mutation == "gate": value["all_sameformat_p010_gates_complete"] = False
            elif mutation == "repeat": value["repeats"] = 3
            elif mutation == "repeat_hash": sample["repeat_sha256"][0] = "e" * 64
            elif mutation == "mapping": sample["UYVA_word_indices_hypothesis"]["Y"] = True
            elif mutation == "mapping_false": sample["UYVA_word_indices_hypothesis"]["Cb"] = False
            elif mutation == "raw": sample["raw_le16_word_positions"]["1"]["center_row_raw_words"][1920] = 65535
            elif mutation == "source": value["inputs"]["Y-x-ascending"]["case_spec"]["signed_slope"] = 8.0
            else: sample["profile_sampling"]["center_row_y"] = 1080.0
            with self.assertRaises(ValueError, msg=mutation): n.analyse_measured(value)

    def test_measured_cli_pins_input_and_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "measured.json"
            output = Path(directory) / "sensitivity.json"
            payload = json.dumps(self.measured_fixture()).encode()
            source.write_bytes(payload)
            done = subprocess.run([sys.executable, n.__file__, str(output), "--measured-report", str(source)], capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            measured = json.loads(output.read_bytes())["measured_pairs"]
            self.assertEqual(measured["input_report_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(measured["geometry_helper_sha256"], hashlib.sha256(Path(geometry.__file__).read_bytes()).hexdigest())
            source.write_text('{"status":"failed"}')
            absent = Path(directory) / "must-not-exist.json"
            failed = subprocess.run([sys.executable, n.__file__, str(absent), "--measured-report", str(source)], capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(absent.exists())


if __name__ == "__main__":
    unittest.main()
