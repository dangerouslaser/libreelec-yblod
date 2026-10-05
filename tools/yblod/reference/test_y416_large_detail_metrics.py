import unittest
import y416_large_detail_metrics as metrics
import hardware_y416_large_detail as runner


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

    def fixture(self, corpus):
        report = {"schema": "yblod.hardware-y416-large-detail.v1", "status": "complete",
                  "all_sameformat_p010_gates_complete": True, "corpus": corpus,
                  "input_size": [1920, 1080], "output_size": [3840, 2160],
                  "inputs": {}, "results": {"native": {}, "scaled": {}}}
        for case in runner.CORPORA[corpus]:
            report["inputs"][case] = {"case_spec": runner.case_spec(case)}
            for stage, size in (("native", [1920, 1080]), ("scaled", [3840, 2160])):
                report["results"][stage][case] = {
                    "size": size, "bytes": size[0] * size[1] * 8,
                    "repeat_stable": True, "sha256": "0" * 64, "repeat_sha256": ["0" * 64] * 2,
                    "profile_sampling": {"center_row_y": size[1] // 2, "center_column_x": size[0] // 2},
                    "UYVA_word_indices_hypothesis": {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3},
                    "raw_le16_word_positions": {str(i): {"center_row_raw_words": [32768] * size[0],
                                                         "center_column_raw_words": [32768] * size[1]} for i in range(4)}}
        return report

    def test_aggregate_all_three_corpora(self):
        for corpus in ("descending", "edges", "stripes"):
            result = metrics.analyse_report(self.fixture(corpus))
            self.assertEqual(result["status"], "complete")

    def test_bad_profile_coordinates_and_source_declarations(self):
        for field in ("profile", "spec", "hash"):
            report = self.fixture("descending")
            if field == "profile": report["results"]["native"]["Y-x-descending"]["profile_sampling"]["center_row_y"] = 540.0
            elif field == "spec": report["inputs"]["Y-x-descending"]["case_spec"]["band_first_code"] = 888.0
            else: report["results"]["native"]["Y-x-descending"]["sha256"] = "x" * 64
            with self.assertRaises(ValueError): metrics.analyse_report(report)


if __name__ == "__main__":
    unittest.main()
