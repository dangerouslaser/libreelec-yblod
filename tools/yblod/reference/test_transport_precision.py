import json
import unittest

import numpy as np

from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET
from transport_precision import audit, coordinate_masks, finish, main, new_accumulator, update
import test_diagnose_frame


class PrecisionArithmeticTests(unittest.TestCase):
    def test_literal_carry_borrow_and_absolute_nonadditivity(self):
        result = new_accumulator()
        update(result, np.array([16, 15, 4095, 0], np.uint16), np.array([15, 16, 0, 4095], np.uint16))
        report = finish(result)
        signed = report["signed_decomposition"]
        self.assertTrue(signed["identity_exact"])
        self.assertTrue(signed["per_bit_identity_exact"])
        self.assertEqual(signed["delta12_sum"], 0)
        self.assertEqual(signed["weighted_high8_sum"], 0)
        self.assertEqual(signed["low4_sum"], 0)
        self.assertEqual(report["absolute_errors_not_additive"], {
            "mean_delta12_codes": 2048, "mean_weighted_high8_codes": 2048, "mean_low4_codes": 15})
        self.assertEqual(report["events"]["opposite_signed_components"], 2)
        self.assertEqual(report["delta12_histogram_nonzero_bins"], [[-4095, 1], [-1, 1], [1, 1], [4095, 1]])
        for bit in report["bit_counts"]:
            self.assertEqual(bit["xor_count"], 4 if bit["bit"] < 5 else 2)

    def test_signed_per_bit_contributions_explain_a_carry(self):
        result = new_accumulator()
        update(result, np.array([16]), np.array([15]))
        report = finish(result)
        self.assertEqual(report["signed_decomposition"]["delta12_sum"], 1)
        self.assertEqual(report["signed_decomposition"]["weighted_high8_sum"], 16)
        self.assertEqual(report["signed_decomposition"]["low4_sum"], -15)
        self.assertEqual([v["signed_contribution_sum_codes"] for v in report["bit_counts"]],
                         [-1, -2, -4, -8, 16, 0, 0, 0, 0, 0, 0, 0])

    def test_nibble_mod4_and_high_byte_histograms(self):
        result = new_accumulator()
        values = np.arange(4096, dtype=np.uint16)
        update(result, values, values)
        report = finish(result)
        for side in ("generated", "capture"):
            self.assertEqual(report["values"][side]["code_mod16_histogram"], [256]*16)
            self.assertEqual(report["values"][side]["code_mod4_histogram"], [1024]*4)
            self.assertEqual(report["values"][side]["high8_histogram"], [16]*256)
        self.assertEqual(report["events"]["identical"], 4096)
        self.assertEqual(report["delta12_histogram_nonzero_bins"], [[0, 4096]])
        for bit in report["bit_counts"]:
            self.assertEqual(bit["generated_set"], 2048)
            self.assertEqual(bit["capture_set"], 2048)
            self.assertEqual(bit["xor_count"], 0)

    def test_empty_accumulator_and_invalid_inputs(self):
        result = new_accumulator()
        update(result, np.array([], dtype=int), np.array([], dtype=int))
        report = finish(result)
        self.assertEqual(report["samples"], 0)
        self.assertIsNone(report["signed_decomposition"]["mean_delta12_codes"])
        self.assertIsNone(report["absolute_errors_not_additive"]["mean_delta12_codes"])
        self.assertEqual(report["delta12_histogram_nonzero_bins"], [])
        for a, b in (([1], [1, 2]), ([1.0], [1]), ([-1], [0]), ([4096], [0])):
            with self.assertRaises(ValueError):
                update(result, np.array(a), np.array(b))
        self.assertEqual(result["samples"], 0)

    def test_multiple_updates_equal_single_batch(self):
        one, strips = new_accumulator(), new_accumulator()
        a, b = np.arange(50, dtype=np.uint16), np.arange(50, 0, -1, dtype=np.uint16)
        update(one, a, b)
        for start in range(0, 50, 7):
            update(strips, a[start:start+7], b[start:start+7])
        self.assertEqual(finish(one), finish(strips))

    def test_masks_use_absolute_rows_and_sample_columns(self):
        masks = coordinate_masks(np.array([49, 50, 51]), np.array([1, 2, 3]))
        np.testing.assert_array_equal(masks["even_row"], [[False]*3, [True]*3, [False]*3])
        np.testing.assert_array_equal(masks["even_sample_column"], [[False, True, False]]*3)
        self.assertEqual(int(masks["row_odd_column_odd"].sum()), 4)
        for rows, cols in (([1.0], [1]), ([-1], [1]), ([1], [-1])):
            with self.assertRaises(ValueError):
                coordinate_masks(np.array(rows), np.array(cols))


class PrecisionBundleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_diagnose_frame.DiagnosisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.fixture.alter(f.output, "output.json", lambda report: report.update(
            target_ycc=TARGET_YCC.tolist(), target_lms=TARGET_LMS.tolist(), target_offset=TARGET_OFFSET.tolist(),
            transport_sampling="P/T co-sited at even x; top-down RGB8"))

    def run_audit(self):
        return audit(self.fixture.output, self.fixture.capture)

    def test_constant_error_exact_decomposition_and_counts(self):
        report = self.run_audit()
        for channel, divisor in (("I", 1), ("P", 2), ("T", 2)):
            group = report["channels"][channel]["all"]
            count = self.fixture.w*(self.fixture.h-48)//divisor
            self.assertEqual(group["samples"], count)
            self.assertEqual(group["signed_decomposition"]["mean_delta12_codes"], 10)
            self.assertEqual(group["signed_decomposition"]["mean_weighted_high8_codes"], 0)
            self.assertEqual(group["signed_decomposition"]["mean_low4_codes"], 10)
            self.assertEqual(group["values"]["generated"]["code_mod16_histogram"][14], count)
            self.assertEqual(group["values"]["capture"]["code_mod16_histogram"][4], count)
            self.assertTrue(all(value == 0 for value in report["even_minus_odd_signed_mean_gaps"][channel].values()))
        self.assertNotIn("packet_hex", report["metadata"])

    def test_odd_crop_parity_and_p_t_have_same_sample_column_coordinates(self):
        f = self.fixture
        rectangle = [2, 49, 124, f.h]
        f.fixture.alter(f.output, "output.json", lambda report: report.update(active_rectangle=rectangle))
        def update_comparison(report):
            report["active_rectangle"] = rectangle
            for channel, divisor in (("I", 1), ("P", 2), ("T", 2)):
                report["channels"][channel]["samples"] = 122*83//divisor
        f.fixture.alter(f.output, "sk4.json", update_comparison)
        f.c[49, 2] = 101  # P sample-column1, odd row.
        f.c[50, 3] = 99   # T sample-column1, even row, though stored at odd x3.
        f.update_capture()
        report = self.run_audit()
        for channel in ("P", "T"):
            groups = report["channels"][channel]
            self.assertEqual(groups["even_row"]["samples"], 61*41)
            self.assertEqual(groups["odd_row"]["samples"], 61*42)
            self.assertEqual(groups["even_sample_column"]["samples"], 30*83)
            self.assertEqual(groups["odd_sample_column"]["samples"], 31*83)
            special = "row_odd_column_odd" if channel == "P" else "row_even_column_odd"
            for name, group in groups.items():
                if name == special:
                    self.assertEqual(group["signed_decomposition"]["delta12_sum"], group["samples"]*10 + (-1 if channel == "P" else 1))
            self.assertEqual(groups["all"]["signed_decomposition"]["delta12_sum"], 61*83*10 + (-1 if channel == "P" else 1))

    def test_capture_hash_or_metadata_corruption_rejected(self):
        f = self.fixture
        f.c.flat[2*1024+10] ^= 1
        f.update_capture()
        with self.assertRaisesRegex(ValueError, "metadata CRC"):
            self.run_audit()
        f.capture.write_bytes(bytes(f.h*f.w*3))
        with self.assertRaisesRegex(ValueError, "capture integrity"):
            self.run_audit()

    def test_changed_baseline_report_or_geometry_rejected(self):
        f = self.fixture
        f.fixture.alter(f.output, "output.json", lambda report: report.update(transport_sampling="unsupported"))
        with self.assertRaisesRegex(ValueError, "packing geometry"):
            self.run_audit()
        path = f.output / "output.json"
        value = json.loads(path.read_text())
        value["transport_sampling"] = "changed without corresponding report hash"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "report hash"):
            self.run_audit()

    def test_cli_report_only_and_exclusive(self):
        f = self.fixture
        destination = f.root / "precision.json"
        before = set(f.root.rglob("*"))
        args = [str(f.output), str(f.capture), "--report", str(destination)]
        main(args)
        self.assertEqual(set(f.root.rglob("*"))-before, {destination})
        original = destination.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(destination.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
