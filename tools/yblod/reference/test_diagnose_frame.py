import json
from pathlib import Path
import unittest

import numpy as np

from compare_output import crc32_mpeg2
from diagnose_frame import accumulate, diagnose, finish, gradient, main, new_total, packet_copies
from extract_frame import digest
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET, pack
import test_compare_regions


def metadata_fixture(y, c):
    payload = bytearray(119)
    offset = 2
    for value in np.rint(TARGET_YCC.reshape(-1) * 8192).astype(int):
        payload[offset:offset+2] = int(value).to_bytes(2, "big", signed=True)
        offset += 2
    for value in np.rint(TARGET_OFFSET * 2**28).astype(int):
        payload[offset:offset+4] = int(value).to_bytes(4, "big")
        offset += 4
    for value in np.rint(TARGET_LMS.reshape(-1) * 16384).astype(int):
        payload[offset:offset+2] = int(value).to_bytes(2, "big", signed=True)
        offset += 2
    for index, header in enumerate((64, 192)):
        body = bytes([header, 0, 0, 0, 0]) + bytes(payload)
        packet = body + crc32_mpeg2(body).to_bytes(4, "big")
        bits = np.unpackbits(np.frombuffer(packet, np.uint8))
        for copy in range(3):
            start = index * 3072 + copy * 1024
            for position, bit in enumerate(bits, start):
                parity = (int(y.flat[position]).bit_count() + (int(c.flat[position]) >> 1).bit_count()) & 1
                c.flat[position] = (int(c.flat[position]) & ~1) | (int(bit) ^ parity)


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_compare_regions.RegionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.output, self.capture = self.fixture.root, self.fixture.direct, self.fixture.capture
        self.h, self.w = self.fixture.h, self.fixture.w
        self.source = np.full((self.h, self.w, 3), .5, dtype="<f4")
        path = self.output / "source.f32le"
        path.write_bytes(self.source.tobytes())
        self.fixture.alter(self.output, "output.json", lambda report: report["stages"].update(
            source_nonlinear={"file": path.name, "shape": [self.h, self.w, 3], "sha256": digest(path)}))
        self.y = np.full((self.h, self.w), 100, dtype=np.uint16)
        self.c = self.y.copy()
        metadata_fixture(self.y, self.c)
        self.update_capture()

    def update_capture(self):
        rgb = np.stack([self.c >> 4, self.y >> 4,
                        (self.y & 15) | ((self.c & 15) << 4)], axis=-1).astype(np.uint8)
        self.capture.write_bytes(rgb[..., [1, 2, 0]].reshape(-1, 8)[:, ::-1].tobytes())
        self.fixture.alter(self.output, "sk4.json", lambda r: r.update(capture_sha256=digest(self.capture)))

    def change_source(self):
        path = self.output / "source.f32le"
        path.write_bytes(self.source.tobytes())
        self.fixture.alter(self.output, "output.json", lambda r: r["stages"]["source_nonlinear"].update(sha256=digest(path)))

    def test_constant_signed_error_counts_histogram_tiles(self):
        report = diagnose(self.output, self.capture)
        self.assertTrue(report["metadata"]["all_crc_valid"])
        for name, divisor in (("I", 1), ("P", 2), ("T", 2)):
            channel = report["channels"][name]
            total = channel["groups"]["all"]
            self.assertEqual(total["mean_signed_codes"], 10)
            self.assertEqual(total["samples"], self.w * (self.h - 48) // divisor)
            self.assertEqual(channel["signed_histogram_nonzero_bins"], [[10, total["samples"]]])
            self.assertEqual(channel["p99_absolute_codes_nearest_rank"], 10)
            self.assertEqual(sum(v["samples"] for k, v in channel["groups"].items() if k.startswith("tile_")), total["samples"])
            self.assertEqual(channel["groups"]["smooth_le_4"]["samples"], total["samples"])
            self.assertIsNone(channel["groups"]["edge_gt_16"]["mean_signed_codes"])

    def test_gradient_includes_neighbours_across_strip_boundary(self):
        # First strip covers rows48..79. A step at80 affects79 and80.
        self.y[80:] = 200
        self.update_capture()
        report = diagnose(self.output, self.capture)
        groups = report["channels"]["I"]["groups"]
        self.assertEqual(groups["edge_gt_16"]["samples"], 2 * self.w)
        self.assertEqual(groups["edge_gt_16"]["mean_signed_codes"], -40)
        self.assertEqual(groups["all"]["negative"], (self.h - 80) * self.w)

    def test_source_domain_chroma_both_use_even_location(self):
        self.source[48:, ::2, 0] = -0.1
        self.change_source()
        report = diagnose(self.output, self.capture)
        for name in ("P", "T"):
            groups = report["channels"][name]["groups"]
            self.assertEqual(groups["source_outside"]["samples"], groups["all"]["samples"])
        groups = report["channels"]["I"]["groups"]
        self.assertEqual(groups["source_outside"]["samples"] * 2, groups["all"]["samples"])

    def test_worst_t_reports_even_coordinate(self):
        self.c[81, 7] = 999
        self.update_capture()
        worst = diagnose(self.output, self.capture)["channels"]["T"]["worst_sample"]
        self.assertEqual(worst, {"x": 6, "y": 81, "signed_codes": -889, "generated": 110, "capture": 999})

    def test_third_packet_copy_corruption_rejected(self):
        self.c.flat[2 * 1024 + 10] ^= 1
        self.update_capture()
        with self.assertRaisesRegex(ValueError, "packet 0 copy 2"):
            diagnose(self.output, self.capture)

    def test_capture_corruption_hash_rejected(self):
        self.capture.write_bytes(bytes(self.h * self.w * 3))
        with self.assertRaisesRegex(ValueError, "capture integrity"):
            diagnose(self.output, self.capture)

    def test_source_stage_hash_rejected(self):
        (self.output / "source.f32le").write_bytes(bytes(self.h * self.w * 12))
        with self.assertRaisesRegex(ValueError, "nonlinear stage integrity"):
            diagnose(self.output, self.capture)

    def test_nonfinite_source_rejected(self):
        self.source[64, 20, 0] = np.nan
        self.change_source()
        with self.assertRaisesRegex(ValueError, "non-finite"):
            diagnose(self.output, self.capture)

    def test_cli_does_not_overwrite_report(self):
        path = self.root / "diagnostic.json"
        args = [str(self.output), str(self.capture), "--report", str(path)]
        main(args)
        original = path.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(path.read_bytes(), original)

    def test_accumulator_signed_values_and_empty(self):
        total = new_total()
        self.assertIsNone(finish(total)["mean_signed_codes"])
        accumulate(total, [-3, -1, 0, 2])
        result = finish(total)
        self.assertEqual(result["mean_signed_codes"], -.5)
        self.assertEqual(result["mean_absolute_codes"], 1.5)
        self.assertEqual(result["negative"], 2)
        self.assertEqual(result["maximum_absolute_codes"], 3)

    def test_gradient_both_axes(self):
        np.testing.assert_array_equal(gradient([[0, 2, 2], [0, 2, 10]]), [[2, 2, 8], [2, 8, 8]])

    def test_metadata_requires_two_full_packets(self):
        with self.assertRaisesRegex(ValueError, "insufficient"):
            packet_copies(np.zeros(100, np.uint16), np.zeros(100, np.uint16))


if __name__ == "__main__":
    unittest.main()
