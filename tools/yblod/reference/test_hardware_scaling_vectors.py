"""Small stdlib-only transport tests; no media frames or remote/GPU jobs."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from hardware_scaling_vectors import NAMES, check_identity, generate, input_bytes, patterns, score_scaled
import scaling_oracle
from scaling_probe import CHANNELS, pack_p010, unpack_p010


class HardwareScalingVectorsTests(unittest.TestCase):
    def test_default64_surface_shapes_depth_and_p010_roundtrip(self):
        cases = patterns()
        self.assertEqual(tuple(cases), NAMES)
        for name, planes in cases.items():
            self.assertEqual((len(planes["Y"][0]), len(planes["Y"])), (64, 64))
            for c in ("Cb", "Cr"):
                self.assertEqual((len(planes[c][0]), len(planes[c])), (32, 32))
            data = pack_p010(planes)
            self.assertEqual(len(data), 64*64*3)
            self.assertEqual(unpack_p010(data, 64, 64), planes, name)
            self.assertTrue(check_identity(planes, data)["exact"])

    def test_configurable_asymmetric_even_sizes(self):
        for width, height in ((2, 2), (4, 6), (128, 64), (66, 130)):
            for planes in patterns(width, height).values():
                data = pack_p010(planes)
                self.assertEqual(unpack_p010(data, width, height), planes)

    def test_constant_nativecodes_and_channel_tags(self):
        cases = patterns(4, 6)
        for name, code in (("zero", 0), ("one", 1), ("neutral", 512), ("maximum", 1023)):
            for c in CHANNELS:
                self.assertEqual(set(s for row in cases[name][c] for s in row), {code})
        for c, code in (("Y", 512), ("Cb", 384), ("Cr", 640)):
            self.assertEqual(cases["channel-tags"][c][0][0], code)

    def test_one_code_step_and_nonwrapping_ramps(self):
        cases = patterns(128, 64)
        for c in CHANNELS:
            self.assertEqual(set(cases["unit-step"][c][0]), {512, 513})
            self.assertEqual(cases["x-ramp"][c][0][0], 384)
            self.assertEqual(cases["x-ramp"][c][0][-1], 640)
            self.assertEqual(cases["y-ramp"][c][0][0], 384)
            self.assertEqual(cases["y-ramp"][c][-1][0], 640)

    def test_identity_detects_single_code_error_and_uv_swap(self):
        planes = patterns(4, 4)["channel-tags"]
        actual = unpack_p010(pack_p010(planes), 4, 4)
        actual["Y"][1][2] += 1
        report = check_identity(planes, pack_p010(actual))
        self.assertFalse(report["exact"])
        self.assertEqual(report["channels"]["Y"]["different"], 1)
        self.assertEqual(report["channels"]["Y"]["maximum_absolute_error"], 1)
        self.assertEqual(report["channels"]["Cb"]["different"], 0)
        actual = dict(planes, Cb=planes["Cr"], Cr=planes["Cb"])
        report = check_identity(planes, pack_p010(actual))
        self.assertEqual(report["channels"]["Cb"]["different"], 4)
        self.assertEqual(report["channels"]["Cr"]["maximum_absolute_error"], 256)

    def test_identity_rejects_lowbits_padding_and_wrong_depth(self):
        planes = patterns(4, 4)["neutral"]
        data = bytearray(pack_p010(planes))
        data[0] |= 1
        with self.assertRaises(ValueError): check_identity(planes, bytes(data))
        with self.assertRaises(ValueError): check_identity(planes, pack_p010(planes)+b"\x00\x00")
        planes["Y"][0][0] = 1024
        with self.assertRaises(ValueError): check_identity(planes, bytes(data))

    def test_input_helper_and_invalid_dimensions(self):
        self.assertEqual(input_bytes("one", 4, 6), pack_p010(patterns(4, 6)["one"]))
        with self.assertRaises(ValueError): input_bytes("missing")
        for dimensions in ((0, 4), (3, 4), (4, -2), (True, 4), (4.0, 4)):
            with self.assertRaises(ValueError): patterns(*dimensions)

    def test_generate_inputs_only_and_optional_expected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"inputs"
            report = generate(root, 4, 6)
            self.assertFalse(report["expected_included"])
            self.assertEqual(json.loads((root/"hardware-probes.json").read_text()), report)
            self.assertEqual((root/"channel-tags-input.p010").read_bytes(), input_bytes("channel-tags", 4, 6))
            self.assertNotIn("expected", report["cases"]["neutral"])
            with self.assertRaises(FileExistsError): generate(root, 4, 6)
            reference = Path(directory)/"expected"
            report = generate(reference, 8, 8, include_expected=True)
            self.assertTrue(report["expected_included"])
            self.assertGreater(report["cases"]["depth-overshoot"]["expected_above_10bit_count"], 0)
            data = (reference/"neutral-expected-Y.u16le").read_bytes()
            self.assertEqual(len(data), 16*16*2)
            self.assertEqual(set(struct.unpack("<"+"H"*256, data)), {512})

    def test_scaled_exact_and_explicit_empty_chroma_interior(self):
        planes = patterns(16, 16)["neutral"]
        expected = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
        report = score_scaled(planes, pack_p010(expected))
        self.assertTrue(report["exact"])
        self.assertEqual(report["expected_above_10bit_count"], 0)
        self.assertEqual(report["channels"]["Y"]["interior"]["samples"], 256)
        self.assertEqual(report["channels"]["Cb"]["interior"]["samples"], 0)
        self.assertIsNone(report["channels"]["Cb"]["interior"]["mean_absolute_error"])
        self.assertEqual(report["channels"]["Cb"]["border"]["samples"], 256)

    def test_scaled_signed_error_parity_and_border_partition(self):
        planes = patterns(16, 16)["neutral"]
        expected = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
        expected["Y"][10][11] += 3  # interior, even row/odd column
        expected["Y"][1][2] -= 2    # border, odd row/even column
        report = score_scaled(planes, pack_p010(expected))
        y = report["channels"]["Y"]
        self.assertFalse(report["exact"])
        self.assertEqual(y["different"], 2)
        self.assertEqual(y["maximum_absolute_error"], 3)
        self.assertEqual(y["mean_signed_error"], 1/1024)
        self.assertEqual(y["interior"]["different"], 1)
        self.assertEqual(y["border"]["different"], 1)
        self.assertEqual(y["interior"]["samples"]+y["border"]["samples"], y["samples"])
        self.assertEqual(y["row_parity"]["0"]["mean_signed_error"], 3/512)
        self.assertEqual(y["row_parity"]["1"]["mean_signed_error"], -2/512)
        self.assertEqual(y["column_parity"]["0"]["mean_signed_error"], -2/512)
        self.assertEqual(y["column_parity"]["1"]["mean_signed_error"], 3/512)

    def test_scaled_rejects_lowbits_and_retains_reference_depth_overflow(self):
        planes = patterns(16, 16)["depth-overshoot"]
        expected = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
        bounded = {c: [[min(s, 1023) for s in row] for row in expected[c]] for c in CHANNELS}
        data = pack_p010(bounded)
        report = score_scaled(planes, data)
        self.assertGreater(report["expected_above_10bit_count"], 0)
        self.assertFalse(report["exact"])
        dirty = bytearray(data)
        dirty[0] |= 1
        with self.assertRaises(ValueError): score_scaled(planes, bytes(dirty))
        with self.assertRaises(ValueError): score_scaled(planes, data+b"\x00\x00")


if __name__ == "__main__":
    unittest.main()
