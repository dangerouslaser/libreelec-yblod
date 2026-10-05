#!/usr/bin/env python3
import copy
from fractions import Fraction
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from make_demo import make_demo
from reference import (inverse_el, map_sample, mmr, polynomial, reconstruct,
                       run, validate)


class ArithmeticTest(unittest.TestCase):
    def test_identity_polynomial_all_input_codes(self):
        for depth in (8, 10):
            for denominator in (15, 20, 32):
                for sample in range(1 << depth):
                    self.assertEqual(polynomial(sample, [0, 1 << denominator], depth, denominator),
                                     sample << (16 - depth))

    def test_quadratic_and_negative_coefficient(self):
        self.assertEqual(polynomial(512, [0, 0, 1 << 20], 10, 20), 16384)
        self.assertEqual(polynomial(512, [1 << 20, -(1 << 20)], 10, 20), 32768)

    def test_mapping_bounds(self):
        self.assertEqual(polynomial(0, [-1, 0], 10, 20), 0)
        self.assertEqual(polynomial(0, [2 << 20, 0], 10, 20), 65535)

    def test_mmr_all_terms_all_orders(self):
        # Independently calculated rational monomials at exactly representable points.
        basis = [Fraction(1, 2), Fraction(1, 4), Fraction(3, 4), Fraction(1, 8),
                 Fraction(3, 8), Fraction(3, 16), Fraction(3, 32)]
        for order in range(1, 4):
            for index, term in enumerate(basis):
                coefficients = [[0] * 7 for _ in range(order)]
                coefficients[-1][index] = 1 << 20
                self.assertEqual(mmr((512, 256, 768), 0, coefficients, 10, 20),
                                 int(term ** order * 65536))

    def test_mmr_large_accumulator_cancellation(self):
        # Individual products exceed signed 64 bits at denominator 32.
        scale = 1 << 32
        coefficients = [[65535 * scale, -65535 * scale, 0, 0, 0, 0, 0]]
        self.assertEqual(mmr((1023, 1023, 0), scale // 4, coefficients, 10, 32), 16384)

    def test_mmr_signed_bounds(self):
        self.assertEqual(mmr((0, 0, 0), -1, [[0] * 7], 10, 20), 0)
        self.assertEqual(mmr((0, 0, 0), 2 << 20, [[0] * 7], 10, 20), 65535)

    def test_neutral_enhancement_is_exact_zero(self):
        for depth in (8, 10):
            for offset in range(1 << depth):
                self.assertEqual(inverse_el(offset, {"offset": offset, "slope": 32768,
                                                    "threshold": 16384, "maximum": 32768}, depth, 20), 0)

    def test_deadzone_and_sign(self):
        parameters = {"offset": 512, "slope": 32768, "threshold": 16384, "maximum": 1 << 19}
        self.assertEqual(inverse_el(513, parameters, 10, 20), 2048)
        self.assertEqual(inverse_el(511, parameters, 10, 20), -2048)

    def test_negative_shift_rounds_down(self):
        parameters = {"offset": 512, "slope": 3, "threshold": 0, "maximum": 1 << 19}
        self.assertEqual(inverse_el(513, parameters, 10, 20), 0)
        self.assertEqual(inverse_el(511, parameters, 10, 20), -1)

    def test_el_depth_scaling(self):
        parameters = {"offset": 128, "slope": 32768, "threshold": 0, "maximum": 1 << 19}
        self.assertEqual(inverse_el(129, parameters, 8, 20), 1024)

    def test_residual_limit_and_signed_storage(self):
        parameters = {"offset": 512, "slope": 32768, "threshold": 0, "maximum": 32768}
        self.assertEqual(inverse_el(1023, parameters, 10, 15), 65536)
        self.assertEqual(inverse_el(0, parameters, 10, 15), -65536)
        parameters["maximum"] = 0
        self.assertEqual(inverse_el(1023, parameters, 10, 15), 0)

    def test_rounding_and_final_bounds(self):
        for depth in (10, 12):
            step = 1 << (16 - depth)
            self.assertEqual(reconstruct(0, step // 2 - 1, depth), 0)
            self.assertEqual(reconstruct(0, step // 2, depth), 1)
            self.assertEqual(reconstruct(0, -65536, depth), 0)
            self.assertEqual(reconstruct(65535, 65536, depth), (1 << depth) - 1)

    def test_no_early_clipping_of_signed_correction(self):
        self.assertEqual(reconstruct(160, -80, 12), 5)


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "input"
        self.manifest = make_demo(self.bundle)

    def save(self):
        path = self.bundle / "frame.json"
        path.write_text(json.dumps(self.manifest))
        return path

    def test_demo_reconstructs_known_samples_and_records_provenance(self):
        report = run(self.save(), self.root / "result")
        raw = (self.root / "result/reconstructed_Y.u16le").read_bytes()
        self.assertEqual(struct.unpack("<8H", raw), (0, 4, 2044, 2048, 2052, 4088, 4092, 2050))
        self.assertEqual(len(report["input_sha256"]), 6)
        self.assertEqual(len(report["stages"]), 12)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(json.loads((self.root / "result/report.json").read_text()), report)

    def test_deterministic_runs(self):
        first = run(self.save(), self.root / "first")
        second = run(self.save(), self.root / "second")
        self.assertEqual(first, second)

    def test_refuses_overwrite(self):
        run(self.save(), self.root / "result")
        with self.assertRaises(FileExistsError):
            run(self.save(), self.root / "result")

    def test_metadata_and_layer_pairing(self):
        for source in ("el", "metadata"):
            for key, value in (("pts", 1), ("frame_id", "other"), ("time_base", [1, 25])):
                bad = copy.deepcopy(self.manifest)
                bad[source][key] = value
                with self.assertRaisesRegex(ValueError, "identities differ"):
                    validate(bad)

    def test_missing_enhancement_is_not_silently_dropped(self):
        self.manifest.pop("el")
        with self.assertRaisesRegex(ValueError, "enhancement layer is required"):
            run(self.save(), self.root / "result")
        self.assertFalse((self.root / "result").exists())

    def test_explicit_residual_disable(self):
        self.manifest.pop("el")
        self.manifest["metadata"]["disable_residual"] = True
        report = run(self.save(), self.root / "result")
        self.assertEqual(report["stages"]["residual_Y"]["minimum"], 0)
        self.assertEqual(report["stages"]["residual_Y"]["maximum"], 0)

    def test_rejects_noninteger_coefficients_and_bad_pivots(self):
        mapping = self.manifest["metadata"]["mappings"][0]
        mapping["segments"][0]["coefficients"][0] = 0.0
        with self.assertRaisesRegex(ValueError, "fixed-point coefficient"):
            validate(self.manifest)
        mapping["segments"][0]["coefficients"][0] = 0
        mapping["pivots"] = [100, 100]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            validate(self.manifest)

    def test_segment_endpoints_and_pivot_clamping(self):
        mappings = self.manifest["metadata"]["mappings"]
        mappings[0] = {"pivots": [100, 512, 900], "segments": [
            {"method": "polynomial", "coefficients": [0, 1 << 20]},
            {"method": "polynomial", "coefficients": [0, 1 << 19]}]}
        for sample, expected in ((0, 6400), (511, 32704), (512, 16384), (900, 28800), (1023, 28800)):
            self.assertEqual(map_sample(0, (sample, 0, 0), mappings, 10, 20), expected)

    def test_mmr_requires_prepared_guide_and_runs_with_it(self):
        self.manifest["metadata"]["mappings"][1]["segments"][0] = {
            "method": "mmr", "constant": 0, "coefficients": [[1 << 20, 0, 0, 0, 0, 0, 0]]}
        with self.assertRaisesRegex(ValueError, "explicitly prepared luma"):
            run(self.save(), self.root / "result")
        (self.bundle / "guide.u16le").write_bytes(struct.pack("<2H", 128, 896))
        self.manifest["mmr_luma"] = "guide.u16le"
        run(self.save(), self.root / "result")
        self.assertEqual(struct.unpack("<2H", (self.root / "result/reconstructed_Cb.u16le").read_bytes()),
                         (512, 3584))

    def test_truncated_and_left_aligned_inputs_rejected(self):
        path = self.bundle / "bl_Y.u16le"
        path.write_bytes(b"\0\0")
        with self.assertRaisesRegex(ValueError, "expected exactly"):
            run(self.save(), self.root / "result")
        path.write_bytes(struct.pack("<8H", *([65535] * 8)))
        with self.assertRaisesRegex(ValueError, "right-aligned"):
            run(self.save(), self.root / "result")

    def test_paths_cannot_escape_bundle(self):
        self.manifest["bl"]["planes"]["Y"] = "../elsewhere"
        with self.assertRaisesRegex(ValueError, "inside the input bundle"):
            run(self.save(), self.root / "result")

    def test_unsupported_modes_rejected(self):
        for key, value in (("transfer", "sdr"), ("format", "p010"), ("width", 3),
                           ("chroma_location", "center"), ("preparation", "")):
            bad = copy.deepcopy(self.manifest)
            bad[key] = value
            with self.assertRaises(ValueError):
                validate(bad)
        for key, value in (("bl_bit_depth", 9), ("output_bit_depth", 11),
                           ("coefficient_log2_denom", 14), ("disable_residual", 0),
                           ("nlq_method", "unknown")):
            bad = copy.deepcopy(self.manifest)
            bad["metadata"][key] = value
            with self.assertRaises(ValueError):
                validate(bad)

    def test_cli_success_and_failure(self):
        script = str(Path(__file__).with_name("reference.py"))
        command = [sys.executable, script, str(self.save()), str(self.root / "result")]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        duplicate = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(duplicate.returncode, 1)
        self.assertNotIn("Traceback", duplicate.stderr)


if __name__ == "__main__":
    unittest.main()
