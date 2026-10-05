import unittest
import y416_large_detail_metrics as metrics


class DetailMetricsTests(unittest.TestCase):
    def test_mirror_uses1016_not1024(self):
        result = metrics.mirror_score([128 * 64, 888 * 64], [888 * 64, 128 * 64])
        self.assertEqual(result["different_samples"], 0)
        self.assertEqual(result["signed_native_code_error_values"], [[0, 1]])

    def test_subcode_mirror_error_preserved(self):
        self.assertEqual(metrics.mirror_score([128 * 64], [888 * 64 + 1])[
            "signed_native_code_error_values"], [[1, 64]])

    def test_step_crop_known_plateaus(self):
        raw = [32768] * 960 + [36864] * 960
        result = metrics.edge_score(raw, [32768] * 1920, "step")
        self.assertEqual(result["crop_slice_start_stop_in_full_profile"], [896, 1024])
        self.assertEqual(result["interior_overshoot_native_codes"], {"numerator": 0, "denominator": 1})

    def test_impulse_absolute_centroid_and_outside_support(self):
        raw = [32768] * 1920
        raw[960] += 4096
        result = metrics.edge_score(raw, [32768] * 1920, "stripe")
        self.assertEqual(result["full_profile_centroid_output_samples"], [960, 1])
        self.assertEqual(result["outside_crop_different_samples"], 0)
        raw[0] += 1
        self.assertEqual(metrics.edge_score(raw, [32768] * 1920, "stripe")["outside_crop_different_samples"], 1)

    def test_declared_integer_translation(self):
        first = [32768] * 3840
        first[1920] = 36864
        second = [32768] * 3840
        second[1924] = 36864
        self.assertEqual(metrics.translation_score(first, second, 4)["different_samples"], 0)
        self.assertGreater(metrics.translation_score(first, second, 2)["different_samples"], 0)

    def test_failed_report_rejected(self):
        with self.assertRaises(ValueError): metrics.analyse_report({"status": "failed"})


if __name__ == "__main__":
    unittest.main()
