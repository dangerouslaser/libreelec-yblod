import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from compare_regions import REGIONS, compare_regions, labels, main
from extract_frame import digest
from output_frame import pack


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.h, self.w = 132, 128
        self.direct, self.bound = self.root / "direct", self.root / "bound"
        self.capture = self.root / "native.rgb"
        reference = pack(np.full((self.h, self.w, 3), 100, dtype=np.uint16))
        native = reference[..., [1, 2, 0]].reshape(-1, 8)[:, ::-1]
        self.capture.write_bytes(native.tobytes())
        self.rgb = np.empty((self.h, self.w, 3), dtype="<f4")
        # Four even-x regions, deliberately different odd-x regions.
        self.rgb[:] = np.tile([[-.1, .5, .5], [1.1, .5, .5],
                              [1.1, .5, .5], [-.1, .5, .5],
                              [-.1, 1.1, .5], [.5, .5, .5],
                              [.5, .5, .5], [-.1, 1.1, .5]], (self.w // 8, 1))
        for path, policy, value in ((self.direct, "direct", 110), (self.bound, "rgb-bound-diagnostic", 102)):
            path.mkdir()
            tunnel = path / "tunnel.rgb8"
            tunnel.write_bytes(pack(np.full((self.h, self.w, 3), value, dtype=np.uint16)).tobytes())
            info = dict(schema="yblod.output-reference.v1", status="complete", policy=policy,
                        identity={"frame_id": "a" * 64 + ":2296", "pts": 2296, "time_base": [1, 1000]},
                        width=self.w, height=self.h, active_rectangle=[0, 48, self.w, self.h],
                        target_ycc=[], target_lms=[], target_offset=[], source_dm={},
                        composer_report_sha256="b" * 64, rpu_sha256="c" * 64,
                        implementation_sha256="d" * 64, numpy_version="test",
                        chroma_expansion="test", pq_domain="test", quantization="test",
                        transport_sampling="test", stages={"unembedded_tunnel": {
                            "file": tunnel.name, "shape": [self.h, self.w, 3], "sha256": digest(tunnel)}})
            if path == self.bound:
                rgb_path = path / "diagnostic_rgb_before_bound.f32le"
                rgb_path.write_bytes(self.rgb.tobytes())
                info["stages"]["diagnostic_rgb_before_bound"] = {
                    "file": rgb_path.name, "shape": [self.h, self.w, 3], "sha256": digest(rgb_path)}
            self.write(path / "output.json", info)
            comparison = dict(identity=info["identity"], policy=policy, active_rectangle=info["active_rectangle"],
                              capture_sha256=digest(self.capture), identity_file_sha256="e" * 64,
                              identity_basis="synthetic fixture", implementation_sha256="f" * 64,
                              output_report_sha256=digest(path / "output.json"),
                              metadata_first_copy_crc=[True, True], transport_matrices_equal=True,
                              channels={name: {"samples": self.w * (self.h - 48) // divisor,
                                               "mean_absolute_codes": value - 100, "rmse_codes": value - 100,
                                               "maximum_absolute_codes": value - 100,
                                               "over_sixteen_codes_percent": 0}
                                        for name, divisor in (("I", 1), ("P", 2), ("T", 2))})
            self.write(path / "sk4.json", comparison)

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def modify_rgb(self, array):
        path = self.bound / "diagnostic_rgb_before_bound.f32le"
        path.write_bytes(array.astype("<f4").tobytes())
        self.alter(self.bound, "output.json", lambda r: r["stages"]["diagnostic_rgb_before_bound"].update(sha256=digest(path)))

    def alter(self, directory, filename, function):
        path = directory / filename
        report = json.loads(path.read_text())
        function(report)
        self.write(path, report)
        if filename == "output.json":
            self.alter(directory, "sk4.json", lambda r: r.update(output_report_sha256=digest(path)))

    def test_exact_regions_strip_boundaries_and_partition(self):
        result = compare_regions(self.direct, self.bound, self.capture)
        self.assertEqual(result["partition_sample_counts"], {"I": 10752, "P": 5376, "T": 5376})
        for region in REGIONS:
            for name, divisor in (("I", 1), ("P", 2), ("T", 2)):
                scores = result["regions"][region][name]
                self.assertEqual(scores["samples"], 2688 // divisor)
                self.assertEqual(scores["direct"]["mean_absolute_codes"], 10)
                self.assertEqual(scores["rgb_bound_diagnostic"]["maximum_absolute_codes"], 2)
                self.assertEqual(scores["change_bound_minus_direct"]["rmse_codes"], -8)

    def test_chroma_regions_use_even_pixel_for_both_channels(self):
        self.rgb[:, ::2] = [-.1, .5, .5]
        self.rgb[:, 1::2] = [1.1, .5, .5]
        self.modify_rgb(self.rgb)
        result = compare_regions(self.direct, self.bound, self.capture)
        for name in ("P", "T"):
            self.assertEqual(result["regions"]["negative-only"][name]["samples"], 5376)
            self.assertEqual(result["regions"]["above-one-only"][name]["samples"], 0)
            self.assertIsNone(result["regions"]["above-one-only"][name]["direct"]["mean_absolute_codes"])
        self.assertEqual(result["regions"]["above-one-only"]["I"]["samples"], 5376)

    def test_boundary_values_and_empty_regions(self):
        self.modify_rgb(np.tile([0, .5, 1], (self.h, self.w, 1)))
        result = compare_regions(self.direct, self.bound, self.capture)
        self.assertEqual(result["regions"]["neither"]["I"]["samples"], 10752)
        for region in REGIONS[1:]:
            for name in ("I", "P", "T"):
                record = result["regions"][region][name]
                self.assertEqual(record["samples"], 0)
                self.assertTrue(all(x is None for x in record["change_bound_minus_direct"].values()))

    def test_unchanged_region_regression_is_visible(self):
        codes = np.full((self.h, self.w, 3), 102, dtype=np.uint16)
        mask = labels(self.rgb) == 0
        codes[mask] = 114
        path = self.bound / "tunnel.rgb8"
        path.write_bytes(pack(codes).tobytes())
        self.alter(self.bound, "output.json", lambda r: r["stages"]["unembedded_tunnel"].update(sha256=digest(path)))
        # One quarter of samples have 14-code error, three quarters 2-code error.
        self.alter(self.bound, "sk4.json", lambda r: [c.update(
            mean_absolute_codes=5, rmse_codes=52 ** .5, maximum_absolute_codes=14)
            for c in r["channels"].values()])
        result = compare_regions(self.direct, self.bound, self.capture)
        for name in ("I", "P", "T"):
            unchanged = result["regions"]["neither"][name]
            self.assertEqual(unchanged["change_bound_minus_direct"]["mean_absolute_codes"], 4)
            changed = result["regions"]["negative-only"][name]
            self.assertEqual(changed["change_bound_minus_direct"]["mean_absolute_codes"], -8)

    def test_nonfinite_active_stage_rejected(self):
        self.rgb[64, 0, 0] = np.nan
        self.modify_rgb(self.rgb)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            compare_regions(self.direct, self.bound, self.capture)

    def test_inactive_regions_not_scored(self):
        self.rgb[:48] = np.nan
        self.modify_rgb(self.rgb)
        result = compare_regions(self.direct, self.bound, self.capture)
        self.assertEqual(result["partition_sample_counts"]["I"], 10752)

    def test_corrupt_capture_rejected(self):
        self.capture.write_bytes(bytes(self.h * self.w * 3))
        with self.assertRaisesRegex(ValueError, "capture integrity"):
            compare_regions(self.direct, self.bound, self.capture)

    def test_corrupt_or_escaping_stage_rejected(self):
        path = self.bound / "diagnostic_rgb_before_bound.f32le"
        path.write_bytes(bytes(self.h * self.w * 12))
        with self.assertRaisesRegex(ValueError, "RGB integrity"):
            compare_regions(self.direct, self.bound, self.capture)
        self.alter(self.bound, "output.json", lambda r: r["stages"]["diagnostic_rgb_before_bound"].update(file="../outside.f32le"))
        with self.assertRaisesRegex(ValueError, "RGB integrity"):
            compare_regions(self.direct, self.bound, self.capture)

    def test_mismatched_pair_rejected(self):
        self.alter(self.bound, "output.json", lambda r: r.update(rpu_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "rpu_sha256"):
            compare_regions(self.direct, self.bound, self.capture)

    def test_labels(self):
        np.testing.assert_array_equal(labels(np.array([[[0, 1, .5], [-1, 0, 0], [0, 2, 0], [-1, 2, 0]]])), [[0, 1, 2, 3]])

    def test_cli_no_overwrite(self):
        path = self.root / "regions.json"
        args = [str(self.direct), str(self.bound), str(self.capture), "--output", str(path)]
        main(args)
        before = path.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
