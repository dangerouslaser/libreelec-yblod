import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np

from output_frame import (TARGET_LMS, TARGET_OFFSET, TARGET_YCC, convert, expand_left,
                          matrix, pack, pq_decode, pq_encode, render, source_matrices)
from extract_frame import digest


def dm_identity():
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
              signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
              signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 8192 if i % 4 == 0 else 0
        dm[f"rgb_to_lms_coef{i}"] = 16384 if i % 4 == 0 else 0
    for i in range(3):
        dm[f"ycc_to_rgb_offset{i}"] = 0
    return dm


class OutputTests(unittest.TestCase):
    def test_pq_known_luminance(self):
        # PQ encodes absolute luminance / 10000 cd/m2.
        self.assertAlmostEqual(float(pq_encode(np.array(.01))), .5080784215, places=9)
        self.assertAlmostEqual(float(pq_decode(np.array(.5080784215))), .01, places=10)

    def test_pq_roundtrip_extended(self):
        values = np.array([.000001, .001, .01, .1, 1., 1.2])
        np.testing.assert_allclose(pq_decode(pq_encode(values)), values, rtol=1e-11)

    def test_pq_negative_policy(self):
        self.assertEqual(float(pq_decode(np.array(-1.))), 0)
        self.assertEqual(float(pq_encode(np.array(-1.))), float(pq_encode(np.array(0.))))

    def test_pq_rejects_nonfinite_and_pole(self):
        for x in (np.nan, np.inf, 100.):
            with self.assertRaises(ValueError):
                pq_decode(np.array(x))

    def test_left_chroma_geometry(self):
        a = np.array([[0., 8.], [16., 24.]])
        np.testing.assert_array_equal(expand_left(a), [[0, 4, 8, 8], [4, 8, 12, 12],
                                                     [12, 16, 20, 20], [16, 20, 24, 24]])

    def test_strip_seams(self):
        a = np.random.default_rng(1).integers(0, 4096, (70, 20))
        full = expand_left(a)
        strips = np.concatenate([expand_left(a, i, min(i+17, 140)) for i in range(0, 140, 17)])
        np.testing.assert_array_equal(full, strips)

    def test_packing_all_12bit_codes(self):
        codes = np.empty((1, 4096, 3), dtype=np.uint16)
        codes[0, :, 0] = np.arange(4096)
        codes[0, :, 1] = np.arange(4096)
        codes[0, :, 2] = 4095 - np.arange(4096)
        rgb = pack(codes)
        i = (rgb[..., 1].astype(int) << 4) | (rgb[..., 2] & 15)
        c = (rgb[..., 0].astype(int) << 4) | (rgb[..., 2] >> 4)
        np.testing.assert_array_equal(i, codes[..., 0])
        np.testing.assert_array_equal(c[:, ::2], codes[:, ::2, 1])
        np.testing.assert_array_equal(c[:, 1::2], codes[:, ::2, 2])

    def test_packing_known_bytes(self):
        a = np.array([[[0xabc, 0x123, 0x456], [0xdef, 0, 0]]])
        np.testing.assert_array_equal(pack(a), [[[0x12, 0xab, 0x3c], [0x45, 0xde, 0x6f]]])

    def test_packing_rejects(self):
        for a in (np.zeros((1, 3, 3), dtype=int), np.full((1, 2, 3), 4096),
                  np.full((1, 2, 3), -1), np.zeros((1, 2, 3))):
            with self.assertRaises(ValueError):
                pack(a)

    def test_target_coordinate_roundtrip(self):
        codes = np.array([[[.3, .55, .48], [.7, .45, .51]]])
        common = matrix(TARGET_LMS, pq_decode(matrix(TARGET_YCC, codes - TARGET_OFFSET)))
        returned = matrix(np.linalg.inv(TARGET_YCC), pq_encode(matrix(np.linalg.inv(TARGET_LMS), common))) + TARGET_OFFSET
        np.testing.assert_allclose(returned, codes, atol=1e-12)

    def test_identity_source_stages(self):
        stages = {}
        convert(np.full((1, 2, 3), 2048), dm_identity(), "direct", lambda n, a: stages.update({n: a}))
        np.testing.assert_array_equal(stages["source_nonlinear"], .5)
        np.testing.assert_allclose(stages["common_linear_lms"], pq_decode(np.array(.5)))

    def test_no_hidden_upper_bound(self):
        stages = {}
        convert(np.full((1, 2, 3), 5000), dm_identity(), "direct", lambda n, a: stages.update({n: a}))
        self.assertGreater(stages["common_linear_lms"].max(), 1)

    def test_reject_unsupported_source(self):
        dm = dm_identity()
        dm["signal_full_range_flag"] = 0
        with self.assertRaises(ValueError):
            source_matrices(dm)

    def test_streamed_render_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, extraction, output = root / "composer", root / "extraction", root / "output"
            result.mkdir()
            extraction.mkdir()
            (extraction / "rpu.json").write_text("{}")
            stages = {}
            for name, shape in (("Y", (132, 8)), ("Cb", (66, 4)), ("Cr", (66, 4))):
                path = result / (name + ".u16le")
                np.full(shape, 2048, dtype="<u2").tofile(path)
                stages[f"reconstructed_{name}"] = {"file": path.name, "sha256": digest(path)}
            report = {"input_manifest": {"height": 132, "width": 8}, "stages": stages}
            (result / "report.json").write_text(json.dumps(report))
            dm = dm_identity()
            dm["cmv29_metadata"] = {"ext_metadata_blocks": [{"Level5": {
                "active_area_left_offset": 2, "active_area_right_offset": 0,
                "active_area_top_offset": 1, "active_area_bottom_offset": 1}}]}
            with patch("output_frame.provenance", return_value=(report, dm, {})):
                info = render(result, extraction, output, "direct")
                with self.assertRaises(FileExistsError):
                    render(result, extraction, output, "direct")
            expected = convert(np.full((132, 8, 3), 2048), dm, "direct", lambda *args: None)
            expected[[0, -1]] = [0, 2048, 2048]
            expected[:, :2] = [0, 2048, 2048]
            actual = np.fromfile(output / "transport_ipt444.u16le", dtype="<u2").reshape(132, 8, 3)
            np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(np.fromfile(output / "unembedded_tunnel.rgb8", dtype="u1").reshape(132, 8, 3), pack(expected))
            for record in info["stages"].values():
                self.assertEqual(digest(output / record["file"]), record["sha256"])


if __name__ == "__main__":
    unittest.main()
