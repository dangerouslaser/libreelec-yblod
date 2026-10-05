"""Independent exact synthetic profiles; no images, NumPy or GPU access."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import y416_edge_metrics as metrics


def fraction(value):
    return Fraction(value["numerator"], value["denominator"])


def profiles(delta, baseline=32768):
    return [baseline + d for d in delta], [baseline] * len(delta)


def fixture_report():
    """Construct the documented aggregate without importing its producer."""
    specs = {"neutral": {"component": None, "axis": None, "kind": "neutral"}}
    for component in ("Y", "Cb", "Cr"):
        for axis in ("x", "y"):
            for kind in ("step", "impulse"):
                specs[f"{component}-{axis}-{kind}"] = {
                    "component": component, "axis": axis, "kind": kind}
    report = {"schema": "yblod.hardware-y416-edges.v1", "status": "complete",
              "all_sameformat_p010_gates_complete": True, "inputs": {}, "results": {}}
    for case, partial in specs.items():
        component = partial["component"]
        spec = dict(partial, baseline_code=512, increment_code=64,
                    change_native_index=None if component is None else (32 if component == "Y" else 16),
                    native_component_sizes={"Y": [64, 64], "Cb": [32, 32], "Cr": [32, 32]},
                    input_size=[64, 64])
        report["inputs"][case] = {"file": case + ".p010", "sha256": "a" * 64, "case_spec": spec}
    for size in (64, 128):
        cases = report["results"][str(size)] = {}
        for case, partial in specs.items():
            positions = {str(index): {"center_row_raw_words": [65535 if index == 3 else 32768] * size,
                                      "center_column_raw_words": [65535 if index == 3 else 32768] * size}
                         for index in range(4)}
            if partial["component"]:
                word = {"Y": "1", "Cb": "0", "Cr": "2"}[partial["component"]]
                key = "center_row_raw_words" if partial["axis"] == "x" else "center_column_raw_words"
                delta = ([0] * (size // 2) + [4096] * (size // 2) if partial["kind"] == "step"
                         else [4096 if i == size // 2 else 0 for i in range(size)])
                positions[word][key] = [32768 + d for d in delta]
            cases[case] = {
                "size": [size, size], "bytes": size * size * 8, "sha256": "b" * 64,
                "repeat_sha256": ["b" * 64, "b" * 64], "repeat_stable": True,
                "profile_sampling": {"center_row_y": size // 2, "center_column_x": size // 2},
                "raw_le16_word_positions": positions,
                "UYVA_word_indices_hypothesis": {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3},
            }
    return report


class ProfileMetricsTests(unittest.TestCase):
    def test_nearest_step_exact_crossings_and_windows(self):
        for size in (64, 128):
            with self.subTest(size=size):
                score = metrics.score_step(*profiles([0] * (size // 2) + [4096] * (size // 2)))
                self.assertTrue(score["unique_interior_rising_crossings"])
                self.assertEqual(fraction(score["width_10_to_90_output_samples"]), Fraction(4, 5))
                middle = score["crossings"]["50"]["events"][0]
                self.assertEqual(fraction(middle["position_samples"]), Fraction(size - 1, 2))
                self.assertEqual(score["plateau_check_windows"]["before"]["slice_start_stop"],
                                 [16, 24] if size == 64 else [16, 32])
                self.assertEqual(fraction(score["plateau_check_windows"]["after"]["maximum_absolute_native_code_error"]), 0)

    def test_triangular_impulse_area_and_centroid_not_normalized(self):
        delta = [0] * 128
        delta[63:66] = [1024, 2048, 1024]
        score = metrics.score_impulse(*profiles(delta))
        self.assertEqual(score["signed_mass_raw"], 4096)
        self.assertEqual(fraction(score["signed_mass_native_codes"]), 64)
        self.assertEqual(fraction(score["centroid_output_samples"]), 64)
        self.assertEqual(score["exact_nonzero_support_inclusive"], [63, 65])
        self.assertEqual(fraction(score["cancellation_ratio"]), 1)

    def test_fractional_native_codes_preserved(self):
        delta = [0] * 64
        delta[31:33] = [1, 2]
        score = metrics.score_impulse(*profiles(delta))
        self.assertEqual(fraction(score["native_code_differences"][31]), Fraction(1, 64))
        self.assertEqual(fraction(score["centroid_output_samples"]), Fraction(95, 3))
        self.assertIsNone(score["greater_than_one_native_code_support_inclusive"])

    def test_ringing_signed_lobes(self):
        delta = [0] * 64
        delta[30:34] = [-64, 1024, 2048, -128]
        score = metrics.score_impulse(*profiles(delta))
        self.assertEqual(score["positive_lobe_mass_raw"], 3072)
        self.assertEqual(score["negative_lobe_magnitude_raw"], 192)
        self.assertEqual(score["signed_mass_raw"], 2880)
        self.assertEqual(score["absolute_mass_raw"], 3264)
        self.assertEqual(fraction(score["centroid_output_samples"]), Fraction(30 * -64 + 31 * 1024 + 32 * 2048 - 33 * 128, 2880))
        self.assertEqual(score["greater_than_one_native_code_support_inclusive"], [31, 33])

    def test_zero_and_negative_mass_centroid_unavailable(self):
        for values in ((-1, 1), (-2, 1), (0, 0)):
            delta = [0] * 64
            delta[31:33] = values
            score = metrics.score_impulse(*profiles(delta))
            self.assertIsNone(score["centroid_output_samples"])
            if sum(values) == 0:
                self.assertIsNone(score["cancellation_ratio"])

    def test_overshoot_and_undershoot_known_amplitude(self):
        delta = [0] * 32 + [4096] * 32
        delta[30], delta[33] = -128, 4352
        score = metrics.score_step(*profiles(delta))
        self.assertEqual(fraction(score["interior_undershoot_native_codes"]), 2)
        self.assertEqual(fraction(score["interior_overshoot_native_codes"]), 4)

    def test_multiple_crossings_are_not_selected_or_fitted(self):
        delta = [0] * 26 + [4096] * 4 + [0] * 4 + [4096] * 30
        score = metrics.score_step(*profiles(delta))
        self.assertEqual([e["direction"] for e in score["crossings"]["50"]["events"]],
                         ["rising", "falling", "rising"])
        self.assertIsNone(score["width_10_to_90_output_samples"])

    def test_threshold_plateau_is_interval_not_fake_single_position(self):
        delta = [0] * 30 + [2048] * 4 + [4096] * 30
        score = metrics.score_step(*profiles(delta))
        middle = score["crossings"]["50"]["events"]
        self.assertEqual(len(middle), 1)
        self.assertEqual(middle[0]["sample_bracket"], [30, 33])
        self.assertIsNone(middle[0]["position_samples"])
        self.assertIsNone(score["width_10_to_90_output_samples"])

    def test_single_equal_sample_crossing_is_counted_once(self):
        score = metrics.score_step(*profiles([0] * 31 + [2048] + [4096] * 32))
        self.assertEqual(len(score["crossings"]["50"]["events"]), 1)
        self.assertEqual(fraction(score["crossings"]["50"]["events"][0]["position_samples"]), 31)

    def test_boundary_touch_and_missing_threshold_do_not_make_width(self):
        for delta in ([2048] * 64, [0] * 64, [0, 4096] + [4096] * 62,
                      [0] * 30 + [2048] + [0] * 3 + [4096] * 30):
            with self.subTest(delta=delta[:3]):
                self.assertIsNone(metrics.score_step(*profiles(delta))["width_10_to_90_output_samples"])

    def test_phase_groups_reconstruct_totals(self):
        delta = [i - 32 for i in range(64)]
        score = metrics.score_impulse(*profiles(delta))
        for period in ("2", "4"):
            groups = score["phase_groups"][period].values()
            self.assertEqual(sum(v["samples"] for v in groups), 64)
            self.assertEqual(sum(v["sum_signed_raw_difference"] for v in groups), sum(delta))

    def test_invalid_profiles_fail_closed(self):
        for bad in ([0] * 63, [0] * 129, [True] * 64, [-1] * 64,
                    [65536] * 64, [1.5] * 64, None):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(ValueError):
                    metrics.score_step(bad, [0] * 64)
        with self.assertRaises(ValueError):
            metrics.score_impulse([0] * 64, [0] * 128)


class AggregateTests(unittest.TestCase):
    def test_canonical_aggregate_and_collateral_reporting(self):
        report = fixture_report()
        report["results"]["128"]["Cb-y-impulse"]["repeat_sha256"] = ["b" * 64] * 4
        report["results"]["128"]["Cb-y-impulse"]["raw_le16_word_positions"]["3"]["center_column_raw_words"][10] -= 1
        result = metrics.analyse_report(report)
        self.assertEqual(result["schema"], "yblod.y416-edge-metrics.v1")
        self.assertEqual(len(result["results"]["64"]), 12)
        score = result["results"]["128"]["Cb-y-impulse"]
        self.assertEqual(score["nominal_output_samples_per_native_component_sample"], 4)
        self.assertEqual(score["collateral_center_profile_changes"]["alpha"]["different_words"], 1)
        self.assertEqual(score["stimulus_raw_word_position"], 0)
        json.dumps(result)  # No non-JSON Fraction instances escape.

    def test_aggregate_rejects_incomplete_or_modified_contract(self):
        changes = (
            lambda r: r.update(status="failed"),
            lambda r: r.update(all_sameformat_p010_gates_complete=False),
            lambda r: r["inputs"].pop("Cr-y-step"),
            lambda r: r["inputs"]["Y-x-step"]["case_spec"].update(increment_code=65),
            lambda r: r["inputs"]["Y-x-step"]["case_spec"].update(change_native_index=True),
            lambda r: r["results"]["64"]["Y-x-step"].update(repeat_stable=False),
            lambda r: r["results"]["64"]["Y-x-step"].update(repeat_sha256=["c" * 64] * 2),
            lambda r: r["results"]["64"]["Y-x-step"]["profile_sampling"].update(center_row_y=31),
            lambda r: r["results"]["64"]["Y-x-step"]["UYVA_word_indices_hypothesis"].update(Y=2),
            lambda r: r["results"]["64"]["Y-x-step"]["raw_le16_word_positions"]["1"].update(center_row_raw_words=[0] * 128),
        )
        for change in changes:
            report = fixture_report()
            change(report)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    metrics.analyse_report(report)

    def test_cli_hashes_exact_input_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.json", Path(directory) / "output.json"
            data = json.dumps(fixture_report(), sort_keys=True).encode()
            source.write_bytes(data)
            metrics.main([str(source), str(output)])
            result = json.loads(output.read_text())
            self.assertEqual(result["input_report_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(result["source_sha256"], hashlib.sha256(Path(metrics.__file__).read_bytes()).hexdigest())
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                metrics.main([str(source), str(output)])
            self.assertEqual(output.read_bytes(), original)

    def test_invalid_cli_input_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.json", Path(directory) / "output.json"
            source.write_text('{"schema":"wrong","status":"complete"}')
            with self.assertRaises(ValueError):
                metrics.main([str(source), str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
