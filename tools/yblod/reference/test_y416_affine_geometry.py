from fractions import Fraction
import unittest
import y416_affine_geometry as geometry


class GeometryTests(unittest.TestCase):
    def test_native_left_chroma_registration(self):
        for component in ("Cb", "Cr"):
            self.assertEqual(geometry.coordinate(20, 64, component, "x", "co-sited"), 10)
            self.assertEqual(geometry.coordinate(20, 64, component, "y", "co-sited"), Fraction(39, 4))

    def test_scaled_luma_registration(self):
        self.assertEqual(geometry.coordinate(20, 128, "Y", "x", "pixel-centre"), Fraction(39, 4))
        self.assertEqual(geometry.coordinate(20, 128, "Y", "x", "annex-b-mixed"), 10)
        self.assertEqual(geometry.coordinate(20, 128, "Y", "y", "annex-b-mixed"), Fraction(39, 4))

    def test_scaled_chroma_four_times_native_grid(self):
        self.assertEqual(geometry.coordinate(20, 128, "Cb", "x", "co-sited"), 5)
        self.assertEqual(geometry.coordinate(20, 128, "Cr", "x", "pixel-centre"), Fraction(39, 8))
        self.assertEqual(geometry.coordinate(20, 128, "Cb", "y", "pixel-centre"), Fraction(37, 8))

    def test_declared_exact_ramp_and_sign_reversal(self):
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                for slope in (-8, 8):
                    values = [int(64 * (512 + slope * geometry.coordinate(i, 128, component, axis, "pixel-centre")))
                              for i in range(128)]
                    score = geometry.score_profile(values, component=component, axis=axis, base=512, slope=slope)
                    self.assertEqual(score["pixel-centre"]["signed_native_code_error_values"], [[0, 1]])

    def test_fractional_words_not_truncated(self):
        values = [int(64 * (512 + 8 * geometry.coordinate(i, 128, "Y", "x", "co-sited"))) + 1
                  for i in range(128)]
        score = geometry.score_profile(values, component="Y", axis="x", base=512, slope=8)
        self.assertEqual(score["co-sited"]["signed_native_code_error_values"], [[1, 64]])

    def test_invalid_profiles_and_coordinates(self):
        for values in ([1] * 63, [True] * 64, [65536] * 64, [1.0] * 64):
            with self.assertRaises(ValueError):
                geometry.score_profile(values, component="Y", axis="x", base=512, slope=8)
        with self.assertRaises(ValueError):
            geometry.coordinate(0, 128, "Y", "x", "fitted")

    def report_fixture(self):
        report = {"schema": "yblod.hardware-y416-spatial.v1", "status": "complete",
                  "inputs": {}, "results": {"64": {}, "128": {}}}
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                for direction, slope in (("ascending", 8), ("descending", -8)):
                    case = f"{component}-{axis}-{direction}"
                    base = 512 - slope * (32 if component == "Y" else 16)
                    report["inputs"][case] = {"case_spec": {
                        "component": component, "axis": axis, "signed_slope": slope,
                        "base_codes_at_origin": {c: base if c == component else 512 for c in ("Y", "Cb", "Cr")}}}
                    for size in (64, 128):
                        values = [int(64 * (base + slope * geometry.coordinate(i, size, component, axis, "pixel-centre")))
                                  for i in range(size)]
                        report["results"][str(size)][case] = {
                            "size": [size, size], "repeat_stable": True,
                            "raw_le16_word_positions": {{"Cb": "0", "Y": "1", "Cr": "2"}[component]: {
                                "center_row_raw_words": values, "center_column_raw_words": values}}}
        return report

    def test_aggregate_scores_both_geometries(self):
        scored = geometry.analyse_report(self.report_fixture())
        for cases in scored["results"].values():
            self.assertEqual(len(cases), 12)
            for models in cases.values():
                self.assertEqual(models["pixel-centre"]["signed_native_code_error_values"], [[0, 1]])

    def test_failed_or_modified_cases_rejected(self):
        report = self.report_fixture()
        report["status"] = "failed"
        with self.assertRaises(ValueError): geometry.analyse_report(report)
        report["status"] = "complete"
        report["inputs"]["Y-x-ascending"]["case_spec"]["base_codes_at_origin"]["Y"] += 1
        with self.assertRaises(ValueError): geometry.analyse_report(report)

    def test_float_metadata_and_unstable_reports_rejected(self):
        for key in ("size", "repeat_stable"):
            report = self.report_fixture()
            report["results"]["64"]["Y-x-ascending"][key] = [64.0, 64] if key == "size" else False
            with self.assertRaises(ValueError): geometry.analyse_report(report)


if __name__ == "__main__":
    unittest.main()
