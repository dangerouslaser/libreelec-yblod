from fractions import Fraction
import unittest
import y416_large_geometry as geometry


class LargeGeometryTests(unittest.TestCase):
    def test_rectangular_scaled_coordinates(self):
        self.assertEqual(geometry.coordinate(2000, 3840, "Y", "x", "pixel-centre"), Fraction(3999, 4))
        self.assertEqual(geometry.coordinate(1000, 2160, "Cb", "y", "pixel-centre"), Fraction(1997, 8))
        self.assertEqual(geometry.coordinate(1000, 2160, "Cr", "y", "co-sited"), Fraction(999, 4))

    def test_exact_bands_and_chroma_expansion(self):
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                source_length = geometry.COMPONENT_SIZES[component][0 if axis == "x" else 1]
                start = source_length // 2 - 48
                for size in (geometry.INPUT[0 if axis == "x" else 1], geometry.INPUT[0 if axis == "x" else 1] * 2):
                    values = [int(64 * (128 + 8 * (min(start + 95, max(start, geometry.coordinate(i, size, component, axis, "pixel-centre"))) - start)))
                              for i in range(size)]
                    score = geometry.score_profile(values, component, axis)
                    self.assertEqual(score["pixel-centre"]["signed_native_code_error_values"], [[0, 1]])
                    expansion = size // source_length
                    self.assertEqual(score["pixel-centre"]["samples"], 96 * expansion - 64)

    def test_fractional_raw_values_retained(self):
        start = 960 - 48
        values = [int(64 * (128 + 8 * (min(start + 95, max(start, geometry.coordinate(i, 3840, "Y", "x", "co-sited"))) - start))) + 1
                  for i in range(3840)]
        result = geometry.score_profile(values, "Y", "x")
        self.assertEqual(result["co-sited"]["signed_native_code_error_values"], [[1, 64]])

    def test_invalid_geometry_and_words(self):
        with self.assertRaises(ValueError): geometry.coordinate(0, 128, "Cb", "y", "co-sited")
        for values in ([True] * 1920, [1.0] * 1920, [65536] * 1920):
            with self.assertRaises(ValueError): geometry.score_profile(values, "Y", "x")

    def fixture(self):
        report = {"schema": "yblod.hardware-y416-large.v1", "status": "complete",
                  "all_sameformat_p010_gates_complete": True, "inputs": {},
                  "results": {"native": {}, "scaled": {}}}
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                case = f"{component}-{axis}-ascending"
                extent = geometry.COMPONENT_SIZES[component][0 if axis == "x" else 1]
                start = extent // 2 - 48
                report["inputs"][case] = {"case_spec": {
                    "component": component, "axis": axis, "signed_slope": 8,
                    "baseline_code": 512, "native_band_length": 96,
                    "band_start_native": start, "band_stop_native_exclusive": start + 96,
                    "source_center_native_index": start + 48, "band_first_code": 128,
                    "band_last_code": 888, "native_component_sizes": geometry.COMPONENT_SIZES,
                    "input_size": geometry.INPUT}}
                for label, size in (("native", geometry.INPUT), ("scaled", [3840, 2160])):
                    length = size[0 if axis == "x" else 1]
                    raw = [int(64 * (128 + 8 * (min(start + 95, max(start,
                           geometry.coordinate(i, length, component, axis, "co-sited"))) - start)))
                           for i in range(length)]
                    report["results"][label][case] = {
                        "size": size, "repeat_stable": True,
                        "profile_sampling": {"center_row_y": size[1] // 2, "center_column_x": size[0] // 2},
                        "raw_le16_word_positions": {geometry.WORDS[component]: {
                            "center_row_raw_words" if axis == "x" else "center_column_raw_words": raw}}}
        return report

    def test_aggregate_exact_hypothesis(self):
        results = geometry.analyse_report(self.fixture())
        for cases in results["results"].values():
            self.assertEqual(len(cases), 6)
            for models in cases.values():
                self.assertEqual(models["co-sited"]["signed_native_code_error_values"], [[0, 1]])

    def test_float_metadata_and_ungated_reports_rejected(self):
        for field in ("profile", "spec", "gate"):
            report = self.fixture()
            if field == "profile": report["results"]["native"]["Y-x-ascending"]["profile_sampling"]["center_row_y"] = 540.0
            elif field == "spec": report["inputs"]["Y-x-ascending"]["case_spec"]["signed_slope"] = 8.0
            else: report["all_sameformat_p010_gates_complete"] = False
            with self.assertRaises(ValueError): geometry.analyse_report(report)


if __name__ == "__main__":
    unittest.main()
