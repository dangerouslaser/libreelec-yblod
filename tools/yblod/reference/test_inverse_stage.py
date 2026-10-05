import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from extract_frame import digest
from inverse_stage import (add, checked_map, co_sited, diagnose, finish, in_unit_domain,
                           inverse_codes, main, total)
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET, convert, pack
import test_diagnose_frame
from test_output_frame import dm_identity


class InverseMathTests(unittest.TestCase):
    def test_unquantized_forward_inverse_roundtrip(self):
        source = np.array([[[1024., 1024., 1024.], [2000., 2200., 2300.]]])
        stages = {}
        convert(source, dm_identity(), "direct", lambda name, a: stages.update({name: a}))
        recovered, valid, counts = inverse_codes(stages["transport_before_quantization"] * 4096, dm_identity())
        self.assertTrue(valid.all())
        self.assertEqual(counts["valid"], 2)
        np.testing.assert_allclose(recovered, source, atol=1e-8)

    def test_quantized_roundtrip_control(self):
        source = np.array([[[1024., 1024., 1024.], [2000., 2200., 2300.]]])
        codes = convert(source, dm_identity(), "direct", lambda *_: None)
        recovered, valid, _ = inverse_codes(codes, dm_identity())
        self.assertTrue(valid.all())
        self.assertLess(np.abs(recovered-source).max(), 2.)

    def test_target_domain_is_excluded_not_clipped(self):
        recovered, valid, counts = inverse_codes(np.array([[[0, 0, 0], [4095, 4095, 4095]]]), dm_identity())
        self.assertFalse(valid.any())
        self.assertTrue(np.isnan(recovered).all())
        self.assertEqual(counts["target_nonlinear_outside_unit_domain"], 2)

    def test_source_inverse_domain_is_excluded(self):
        dm = dm_identity()
        for i in (0, 4, 8):
            dm[f"rgb_to_lms_coef{i}"] = 8192
        recovered, valid, counts = inverse_codes(np.array([[[4000, 2048, 2048]]]), dm)
        self.assertFalse(valid.any())
        self.assertTrue(np.isnan(recovered).all())
        self.assertEqual(counts["source_linear_outside_unit_domain_after_valid_target"], 1)

    def test_nonfinite_and_out_of_code_range_rejected(self):
        for value in (np.nan, np.inf, -1, 4096):
            with self.assertRaises(ValueError):
                inverse_codes(np.full((1, 1, 3), value), dm_identity())

    def test_co_sited_never_uses_odd_intensity(self):
        i = np.array([[1, 999, 2, 888]])
        c = np.array([[10, 20, 30, 40]])
        np.testing.assert_array_equal(co_sited(i, c, 0, 4), [[[1, 10, 20], [2, 30, 40]]])
        with self.assertRaises(ValueError):
            co_sited(i, c, 1, 4)

    def test_strict_unit_domain_and_float_statistics(self):
        np.testing.assert_array_equal(in_unit_domain(np.array([[[0, .5, 1], [-1e-16, .5, 1], [0, np.nan, 1]]])), [[True, False, False]])
        stats = total()
        self.assertIsNone(finish(stats)["mean_signed_codes"])
        add(stats, [-.5, 1.5])
        self.assertEqual(finish(stats)["mean_signed_codes"], .5)
        self.assertEqual(finish(stats)["mean_absolute_codes"], 1.)
        with self.assertRaises(ValueError):
            add(stats, [np.nan])


class InverseBundleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_diagnose_frame.DiagnosisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.result, self.extraction = f.root / "composer", f.root / "extraction"
        self.result.mkdir()
        self.extraction.mkdir()
        self.dm = dm_identity()
        self.report = {"input_manifest": {"height": f.h, "width": f.w}, "stages": {}}
        for name in ("reconstructed_Y", "reconstructed_Cb", "reconstructed_Cr", "mapped_Y", "residual_Y"):
            shape = (f.h//2, f.w//2) if name.endswith(("Cb", "Cr")) else (f.h, f.w)
            value = 0 if name == "residual_Y" else 1024 * (16 if name == "mapped_Y" else 1)
            dtype = "<i4" if name == "residual_Y" else "<u2"
            path = self.result / (name + ".raw")
            path.write_bytes(np.full(shape, value, dtype=dtype).tobytes())
            self.report["stages"][name] = {"file": path.name, "sha256": digest(path)}
        (self.result / "report.json").write_text(json.dumps(self.report))
        (self.extraction / "rpu.json").write_text("{}")
        source = np.full((f.h, f.w, 3), 1024.)
        codes = convert(source, self.dm, "direct", lambda *_: None)
        tunnel = f.output / "tunnel.rgb8"
        tunnel.write_bytes(pack(codes).tobytes())
        f.y = codes[..., 0].copy()
        f.c[:, ::2], f.c[:, 1::2] = codes[:, ::2, 1], codes[:, ::2, 2]
        test_diagnose_frame.metadata_fixture(f.y, f.c)
        f.update_capture()
        def update(info):
            info.update(source_dm=self.dm, composer_report_sha256=digest(self.result / "report.json"),
                        rpu_sha256=digest(self.extraction / "rpu.json"),
                        target_ycc=TARGET_YCC.tolist(), target_lms=TARGET_LMS.tolist(), target_offset=TARGET_OFFSET.tolist(),
                        chroma_expansion="bilinear-left-edge-replicated-float64")
            info["stages"]["unembedded_tunnel"]["sha256"] = digest(tunnel)
        f.fixture.alter(f.output, "output.json", update)
        self.identity = json.loads((f.output / "output.json").read_text())["identity"]
        # The production provenance function is tested by output_frame tests.
        # This fixture isolates inverse diagnostics while retaining real hashes.
        patcher = patch("inverse_stage.provenance", return_value=(self.report, self.dm, self.identity))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_diagnosis(self):
        return diagnose(self.fixture.output, self.result, self.extraction, self.fixture.capture)

    def test_identical_tunnel_control_and_shared_sample_count(self):
        result = self.run_diagnosis()
        self.assertEqual(result["exclusions"]["union_excluded"], 0)
        for channel in ("Y", "Cb", "Cr"):
            comparison = result["comparisons"]["capture_minus_generated_roundtrip"][channel]
            self.assertEqual(comparison["all"]["maximum_absolute_codes"], 0)
            self.assertEqual(comparison["all"]["samples"], self.fixture.w * (self.fixture.h - 48) // 2)
            self.assertEqual(comparison["even_row"]["samples"] + comparison["odd_row"]["samples"], comparison["all"]["samples"])
        self.assertEqual(result["Y_enhancement_hypotheses"]["expected_enhancement_Y"]["maximum_absolute_codes"], 0)

    def test_provenance_hash_mismatch_rejected(self):
        (self.extraction / "rpu.json").write_text("{\"changed\":true}")
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.run_diagnosis()

    def test_captured_endpoint_with_valid_inverse_is_excluded_everywhere(self):
        f = self.fixture
        f.y[48, 0] = 0
        f.c[48, 0:2] = 2048
        f.update_capture()
        result = self.run_diagnosis()
        excluded = result["exclusions"]
        self.assertEqual(excluded["capture_transport_boundary"], 1)
        self.assertEqual(excluded["capture_inverse_domain"], 0)
        self.assertEqual(excluded["union_excluded"], 1)
        expected = f.w * (f.h - 48) // 2 - 1
        for comparison in result["comparisons"].values():
            for channel in comparison.values():
                self.assertEqual(channel["all"]["samples"], expected)
        for hypothesis in result["Y_enhancement_hypotheses"].values():
            self.assertEqual(hypothesis["samples"], expected)

    def test_reconstruction_file_mismatch_rejected(self):
        (self.result / "mapped_Y.raw").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "stage integrity"):
            self.run_diagnosis()

    def test_saved_y_composition_mismatch_rejected(self):
        path = self.result / "residual_Y.raw"
        path.write_bytes(np.full((self.fixture.h, self.fixture.w), 16, dtype="<i4").tobytes())
        self.report["stages"]["residual_Y"]["sha256"] = digest(path)
        with self.assertRaisesRegex(ValueError, "composition arithmetic"):
            self.run_diagnosis()

    def test_cli_exclusive_report(self):
        path = self.fixture.root / "inverse.json"
        args = [str(self.fixture.output), str(self.result), str(self.extraction), str(self.fixture.capture), "--report", str(path)]
        main(args)
        before = path.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
