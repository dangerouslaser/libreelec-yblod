import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from extract_frame import digest, save_json
from import_rpu import normalize
from prepare_frame import (H_OFFSETS, H_WEIGHTS, chroma_to_left, fir, mmr_luma_left,
                           plane, prepare, upsample_el)
from test_import_rpu import synthetic_rpu


def scalar_fir(values, axis, offsets, weights, shift, maximum):
    rows, cols = values.shape
    result = np.empty_like(values, dtype=np.int64)
    for y in range(rows):
        for x in range(cols):
            total = 0
            for delta, coefficient in zip(offsets, weights):
                yy = min(rows - 1, max(0, y + delta)) if axis == 0 else y
                xx = min(cols - 1, max(0, x + delta)) if axis == 1 else x
                total += int(values[yy, xx]) * coefficient
            result[y, x] = min(maximum, max(0, (total + 2 ** (shift - 1)) // 2 ** shift))
    return result


class FilterTest(unittest.TestCase):
    def test_constant_preservation_including_edges(self):
        for value in (0, 1, 512, 1023, 65535):
            for channel in ("Y", "Cb", "Cr"):
                result, vertical, _ = upsample_el(np.full((3, 5), value), channel)
                np.testing.assert_array_equal(result, np.full((6, 10), value))
                np.testing.assert_array_equal(vertical, np.full((6, 5), value))

    def test_vectorized_filters_against_scalar_integer_oracle(self):
        rng = np.random.default_rng(487)
        values = rng.integers(0, 1024, (9, 11), dtype=np.int64)
        for axis, offsets, weights, shift in ((0, (-2, -1, 0, 1), (-3, 29, 111, -9), 7),
                                              (0, (-1, 0, 1, 2), (-9, 111, 29, -3), 7),
                                              (0, (-1, 0), (64, 192), 8),
                                              (0, (0, 1), (192, 64), 8),
                                              (1, H_OFFSETS, H_WEIGHTS, 12)):
            expected = scalar_fir(values, axis, offsets, weights, shift, 65535)
            np.testing.assert_array_equal(fir(values, axis, offsets, weights, shift, 65535)[0], expected)

    def test_quarter_row_chroma_shift_direction(self):
        ramp = np.repeat((np.arange(8) * 128)[:, None], 3, axis=1)
        for method in ("linear", "cubic128"):
            shifted, _ = chroma_to_left(ramp, "topleft", 10, method)
            np.testing.assert_array_equal(shifted[2:5], ramp[2:5] + 32)
            self.assertEqual(int(shifted[2, 1]), 288)
        identity, _ = chroma_to_left(ramp, "left", 10, "linear")
        np.testing.assert_array_equal(identity, ramp)

    def test_luma_and_chroma_vertical_phase_on_ramp(self):
        ramp = np.repeat((200 + np.arange(8) * 128)[:, None], 8, axis=1)
        for channel in ("Y", "Cb", "Cr"):
            _, vertical, _ = upsample_el(ramp, channel)
            self.assertEqual(int(vertical[4, 3]), 424)
            self.assertEqual(int(vertical[5, 3]), 488)

    def test_horizontal_cosited_even_and_half_phase_odd(self):
        values = np.tile(200 + np.arange(12) * 16, (4, 1))
        result, vertical, _ = upsample_el(values, "Cb")
        np.testing.assert_array_equal(result[:, ::2], vertical)
        self.assertEqual(int(result[3, 10]), 280)
        self.assertEqual(int(result[3, 11]), 288)

    def test_mmr_luma_positions_and_border_replication(self):
        y, x = np.indices((8, 8))
        values = y * 40 + x * 4
        guide, _ = mmr_luma_left(values)
        self.assertEqual(int(guide[0, 0]), 21)
        self.assertEqual(int(guide[1, 1]), 108)
        self.assertEqual(int(guide[3, 3]), 284)

    def test_mmr_luma_rounds_each_pass(self):
        values = np.array([[0, 0, 1, 0], [0, 0, 0, 0]])
        guide, _ = mmr_luma_left(values)
        # Horizontal 2/4 rounds to 1, then (1+0)/2 rounds to 1.
        # Combining both passes before rounding would incorrectly yield 0.
        self.assertEqual(int(guide[0, 1]), 1)

    def test_no_implicit_declared_depth_clamp_in_annex_b(self):
        values = np.tile([0, 0, 0, 1023, 1023, 1023, 1023, 1023], (4, 1))
        result, _, _ = upsample_el(values, "Cb")
        self.assertGreater(int(result.max()), 1023)
        self.assertLessEqual(int(result.max()), 65535)

    def test_invalid_planes_and_filters_rejected(self):
        for values in (np.ones((2, 2), dtype=float), np.zeros((0, 2), dtype=int),
                       np.array([[-1]]), np.array([[65536]])):
            with self.assertRaises(ValueError):
                plane(values)
        with self.assertRaises(ValueError):
            chroma_to_left(np.zeros((2, 2), dtype=int), "center", 10, "linear")
        with self.assertRaises(ValueError):
            mmr_luma_left(np.zeros((3, 2), dtype=int))


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "extracted"
        self.source.mkdir()
        rpu = synthetic_rpu()
        rpu["header"]["chroma_resampling_explicit_filter_flag"] = False
        save_json(self.source / "rpu.json", rpu)
        (self.source / "frame.rpu.bin").write_bytes(b"synthetic-rpu")
        identity = {"frame_id": "synthetic-hash:0", "pts": 0, "time_base": [1, 24]}
        self.extraction = {"schema": "yblod.extracted-frame.v1", "status": "complete",
            "source_sha256": "synthetic-hash", "source_packet_index_zero_based": 0,
            "pts": 0, "time_base": [1, 24], "rpu_matches_source_packet_and_global_index": True,
            "rpu_sha256": digest(self.source / "frame.rpu.bin"),
            "rpu_json_sha256": digest(self.source / "rpu.json"), "layers": {}}
        for layer, shape in (("bl", (4, 8)), ("el", (2, 4))):
            records = {}
            for channel in ("Y", "Cb", "Cr"):
                h, w = shape if channel == "Y" else (shape[0] // 2, shape[1] // 2)
                values = np.full((h, w), 512, dtype="<u2")
                filename = f"{layer}_{channel}.u16le"
                (self.source / filename).write_bytes(values.tobytes())
                records[channel] = {"file": filename, "sha256": digest(self.source / filename)}
            self.extraction["layers"][layer] = {"width": shape[1], "height": shape[0],
                "chroma_location": "topleft", "stream": {"color_transfer": "smpte2084"}, "planes": records}
        save_json(self.source / "extraction.json", self.extraction)
        self.composition = {"metadata": normalize(rpu, identity),
                            "source_extraction_sha256": digest(self.source / "extraction.json")}
        save_json(self.source / "composition.json", self.composition)
        (self.source / "verification").mkdir()
        self.verification = {"status": "complete", "metadata_normalization_exact": True,
            "extraction_sha256": digest(self.source / "extraction.json"),
            "composition_sha256": digest(self.source / "composition.json"),
            "layers": {c: {"single_and_four_thread_decodes_identical": True} for c in ("bl", "el")}}
        save_json(self.source / "verification/verification.json", self.verification)

    def test_prepares_aligned_bundle_and_hardware_checkpoint(self):
        manifest = prepare(self.source, self.root / "prepared", "linear")
        self.assertEqual(manifest["chroma_location"], "left")
        details = manifest["preparation_details"]
        self.assertEqual(details["native_chroma_locations"], {"bl": "topleft", "el": "topleft"})
        self.assertEqual(details["stages"]["el_Y"]["width"], 8)
        self.assertEqual(details["stages"]["el_Y"]["height"], 4)
        self.assertEqual(digest(self.root / "prepared/bl_Y.u16le"),
                         digest(self.source / "bl_Y.u16le"))
        job = json.loads((self.root / "prepared/el-scaling-job.json").read_text())
        self.assertEqual(job["input"]["width"], 4)
        self.assertEqual(job["output"]["width"], 8)
        self.assertTrue(job["does_not_apply_rpu_or_combine_layers"])

    def test_refuses_changed_plane_and_existing_destination(self):
        prepare(self.source, self.root / "prepared", "linear")
        with self.assertRaises(FileExistsError):
            prepare(self.source, self.root / "prepared", "linear")
        (self.source / "el_Y.u16le").write_bytes(np.full((2, 4), 513, dtype="<u2").tobytes())
        with self.assertRaisesRegex(ValueError, "original plane changed"):
            prepare(self.source, self.root / "bad", "linear")
        self.assertFalse((self.root / "bad").exists())

    def test_refuses_changed_instructions(self):
        composition = copy.deepcopy(self.composition)
        composition["metadata"]["nlq"][0]["slope"] += 1
        (self.source / "composition.json").write_text(json.dumps(composition))
        with self.assertRaisesRegex(ValueError, "provenance mismatch"):
            prepare(self.source, self.root / "bad", "linear")


if __name__ == "__main__":
    unittest.main()
