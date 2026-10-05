import json
from pathlib import Path
import struct
import tempfile
import unittest

from scaling_probe import (CHANNELS, generate, pack_p010, patterns, score,
                           sha, unpack_p010)

try:
    import numpy as np
    from prepare_frame import chroma_to_left, upsample_el as production_scale
except ImportError:
    np = None


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def outputs(self, bundle, manifest):
        out = self.root / "outputs"
        out.mkdir()
        for name, case in manifest["cases"].items():
            planes = {}
            for c in CHANNELS:
                w, h = (32, 32) if c == "Y" else (16, 16)
                data = (bundle / case["expected"][c]["file"]).read_bytes()
                values = struct.unpack("<" + "H" * (w * h), data)
                # Explicit fake backend clamp ONLY in this test. The tool does
                # not alter expected values or silently apply this policy.
                planes[c] = [[min(1023, s) for s in values[y * w:(y + 1) * w]] for y in range(h)]
            (out / case["backend_output_file"]).write_bytes(pack_p010(planes))
        return out

    def test_p010_roundtrip_and_uv_order(self):
        planes = {"Y": [[0, 1], [512, 1023]], "Cb": [[63]], "Cr": [[1000]]}
        data = pack_p010(planes)
        self.assertEqual(struct.unpack("<6H", data), (0, 64, 32768, 65472, 4032, 64000))
        self.assertEqual(unpack_p010(data, 2, 2), planes)

    def test_p010_rejects_depth_padding_precision_and_dimensions(self):
        with self.assertRaises(ValueError): pack_p010({"Y": [[1024, 1], [0, 1]], "Cb": [[0]], "Cr": [[0]]})
        data = pack_p010({"Y": [[0, 1], [0, 1]], "Cb": [[0]], "Cr": [[0]]})
        for bad in (data + b"\0\0", data[:-2], b"\1\0" + data[2:]):
            with self.assertRaises(ValueError): unpack_p010(bad, 2, 2)
        with self.assertRaises(ValueError): unpack_p010(data, 1, 2)

    def test_generate_is_exclusive_and_inputs_are_unmodified_codes(self):
        bundle = self.root / "probes"
        manifest = generate(bundle)
        self.assertEqual(set(manifest["cases"]), set(patterns()))
        for name, planes in patterns().items():
            self.assertEqual(unpack_p010((bundle / manifest["cases"][name]["input"]["file"]).read_bytes(), 16, 16), planes)
        self.assertGreater(manifest["cases"]["depth-overshoot"]["expected_above_10bit_count"], 0)
        with self.assertRaises(FileExistsError): generate(bundle)

    def test_score_exact_and_explicit_depth_stress(self):
        bundle = self.root / "probes"
        manifest = generate(bundle)
        out = self.outputs(bundle, manifest)
        report = score(bundle, out, "synthetic unit-test backend, explicit10bit clamp, not hardware")
        self.assertEqual(report["status"], "complete")
        for name, case in report["cases"].items():
            for c in CHANNELS:
                different = case["channels"][c]["different"]
                if name != "depth-overshoot": self.assertEqual(different, 0)
        self.assertGreater(sum(r["different"] for r in report["cases"]["depth-overshoot"]["channels"].values()), 0)

    def test_score_rejects_hash_corruption_missing_output_and_empty_provenance(self):
        bundle = self.root / "probes"
        manifest = generate(bundle)
        out = self.outputs(bundle, manifest)
        with self.assertRaises(ValueError): score(bundle, out, "")
        path = bundle / manifest["cases"]["neutral"]["expected"]["Y"]["file"]
        original = path.read_bytes()
        path.write_bytes(b"\1\0" + original[2:])
        with self.assertRaises(ValueError): score(bundle, out, "test")
        path.write_bytes(original)
        (out / "neutral-output.p010").unlink()
        with self.assertRaises(FileNotFoundError): score(bundle, out, "test")

    def test_score_rejects_path_escape_and_incomplete_contract(self):
        bundle = self.root / "probes"
        manifest = generate(bundle)
        out = self.outputs(bundle, manifest)
        manifest["cases"]["neutral"]["input"]["file"] = "../outside.p010"
        (bundle / "probes.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): score(bundle, out, "test")
        manifest["cases"].pop("impulse")
        (bundle / "probes.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "contract"): score(bundle, out, "test")

    def test_score_rejects_rehashed_expected_and_semantic_or_codepin_changes(self):
        bundle = self.root / "probes"
        manifest = generate(bundle)
        out = self.outputs(bundle, manifest)
        record = manifest["cases"]["neutral"]["expected"]["Y"]
        path = bundle / record["file"]
        changed = b"\1\0" + path.read_bytes()[2:]
        path.write_bytes(changed)
        record["sha256"] = sha(changed)
        (bundle / "probes.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "independent oracle"): score(bundle, out, "test")
        for key in ("range", "input_chroma_location", "generator_sha256", "oracle_sha256"):
            altered = dict(manifest, **{key: "changed"})
            (bundle / "probes.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "contract"): score(bundle, out, "test")


@unittest.skipIf(np is None, "NumPy unavailable")
class PhysicalRegistrationTest(unittest.TestCase):
    def test_common_physical_affine_field_and_wrong_phase_controls(self):
        # F(x,y)=128+8x+32y. EL luma u maps to BL2u+1/2;
        # horizontal coordinates are co-sited. Derive sources from geometry,
        # not from renderer taps or a hardware capture.
        by, bx = np.indices((32, 32))
        ey, ex = np.indices((16, 16))
        bl_y = 128 + 8 * bx + 32 * by
        el_y = 128 + 16 * ex + 32 * (2 * ey) + 16
        # Use16bit values for geometry fixture; no claim this is a10bit movie.
        scaled_y, _, _ = production_scale(el_y, "Y")
        np.testing.assert_array_equal(scaled_y[6:24, 8:24], bl_y[6:24, 8:24])
        cy, cx = np.indices((16, 16))
        dy, dx = np.indices((8, 8))
        bl_c = 128 + 16 * cx + 64 * cy
        el_c = 144 + 32 * dx + 128 * dy
        bl_left, _ = chroma_to_left(bl_c, "topleft", 16, "linear")
        el_left, _ = chroma_to_left(el_c, "topleft", 16, "linear")
        twice, _ = chroma_to_left(el_left, "topleft", 16, "linear")
        for input_c, difference in ((el_c, -32), (el_left, 0), (twice, 32)):
            actual, _, _ = production_scale(input_c, "Cb")
            np.testing.assert_array_equal(actual[4:10, 6:10], bl_left[4:10, 6:10] + difference)
        self.assertEqual(int(bl_left[5, 7]), 144 + 16 * 7 + 64 * 5)


if __name__ == "__main__":
    unittest.main()
