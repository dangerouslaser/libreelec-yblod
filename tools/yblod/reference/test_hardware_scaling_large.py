"""Small exact oracle and fake subprocess checks; no GPU/movie frames."""
from array import array
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_scaling_large as large
import scaling_oracle
from scaling_probe import CHANNELS, pack_p010, unpack_p010


class LargeSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def planes(self, pattern, width=64, height=64):
        return {c: [[large.source_code(pattern, c, x, y, width, height)
                     for x in range(width if c == "Y" else width//2)]
                    for y in range(height if c == "Y" else height//2)] for c in CHANNELS}

    def test_generation_stream_matches_canonical_p010_and_bounds(self):
        for pattern in large.PATTERNS:
            path = self.root/f"{pattern}.p010"
            record = large.generate(path, pattern, 64, 64)
            self.assertEqual(path.read_bytes(), pack_p010(self.planes(pattern)))
            self.assertEqual(record["sha256"], large.file_hash(path))
            measured = large.scan(path, pattern, 64, 64, 1)
            self.assertTrue(measured["unused_low_bits_zero"])
            for channel in measured["channels"].values():
                self.assertGreaterEqual(channel["minimum_code"], 0)
                self.assertLessEqual(channel["maximum_code"], 1023)

    def test_all_signed_slopes_axes_components_against_separate_pass_fraction_oracle(self):
        # Only one-dimensional expansion is needed: the other axis is constant,
        # yet oracle.expand still executes BOTH passes and intermediate rounding.
        for axis in ("x", "y"):
            for step in (1, 2, 4, 8):
                for descending in (False, True):
                    pattern = f"{axis}-{step}"+("-desc" if descending else "")
                    for c in CHANNELS:
                        extent = 192 if c == "Y" else 96
                        values = [large.source_code(pattern, c, m if axis == "x" else 0,
                                                    m if axis == "y" else 0, 192, 192) for m in range(extent)]
                        rows = [values] if axis == "x" else [[v] for v in values]
                        output, _, _ = scaling_oracle.expand(rows, c)
                        start, length, _, _ = large.band(pattern, c, 192, 192)
                        for m in range(2*start+16, 2*(start+length)-16):
                            actual = output[0][m] if axis == "x" else output[m][0]
                            self.assertEqual(actual, large.expected_code(pattern, c, m if axis == "x" else 0,
                                                                          m if axis == "y" else 0, 192, 192),
                                             (pattern, c, m))

    def test_scan_errors_parity_and_invalid_layout(self):
        pattern = "y-2-desc"
        planes = self.planes(pattern)
        expected = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
        path = self.root/"exact.p010"
        path.write_bytes(pack_p010(expected))
        score = large.scan(path, pattern, 64, 64)
        self.assertTrue(all(c["different"] == 0 for c in score["channels"].values()))
        expected["Y"][40][41] += 3
        path.write_bytes(pack_p010(expected))
        score = large.scan(path, pattern, 64, 64)
        self.assertEqual(score["channels"]["Y"]["different"], 1)
        self.assertEqual(score["channels"]["Y"]["row_parity"]["0"]["sum_signed_error"], 3)
        self.assertEqual(score["channels"]["Y"]["column_parity"]["1"]["sum_signed_error"], 3)
        for bad in (path.read_bytes()[:-1], path.read_bytes()+b"\x00", bytes([1])+path.read_bytes()[1:]):
            path.write_bytes(bad)
            with self.assertRaises(ValueError): large.scan(path, pattern, 64, 64)
            path.write_bytes(pack_p010(expected))

    def test_production_band_extrema_and_dimension_rejection(self):
        for pattern in large.PATTERNS:
            if pattern == "channel-tags": continue
            axis = large.descriptor(pattern)[0]
            for c in CHANNELS:
                start, length, _, _ = large.band(pattern, c, 1920, 1080)
                self.assertEqual(length, 128)
                values = [large.source_code(pattern, c, m if axis == "x" else 0,
                                             m if axis == "y" else 0, 1920, 1080)
                          for m in (0, start, start+length-1, 1919 if axis == "x" else 1079)]
                self.assertGreaterEqual(min(values), 0)
                self.assertLessEqual(max(values), 1023)
                if "-8" in pattern: self.assertEqual(set(values), {0, 1016})
        for dims in ((32, 64), (1922, 1080), (1920, 1082), (65, 64), (64.0, 64)):
            with self.assertRaises(ValueError): large.dimensions(*dims)


class LargeRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root/"fake"
        self.binary.write_bytes(b"synthetic fake, no hardware")
        self.calls, self.fault = [], None

    def fake(self, argv, **kwargs):
        self.assertEqual(kwargs, {"capture_output": True, "timeout": 60, "check": False})
        self.calls.append(argv)
        iw, ih, ow, oh = map(int, argv[4:8])
        copy = argv[8] == "copy"
        i, o = ("left", "left") if copy else (argv[10], argv[12])
        if iw == ow: shutil.copyfile(argv[2], argv[3])
        else:
            source = unpack_p010(Path(argv[2]).read_bytes(), iw, ih)
            output = {c: [[source[c][y//2][x//2] for x in range(ow if c == "Y" else ow//2)]
                          for y in range(oh if c == "Y" else oh//2)] for c in CHANNELS}
            Path(argv[3]).write_bytes(pack_p010(output))
        if self.fault == "top-left-identity" and not copy and i == o == "top-left" and iw == ow:
            data = bytearray(Path(argv[3]).read_bytes()); data[0:2] = (513<<6).to_bytes(2, "little")
            Path(argv[3]).write_bytes(data)
        if self.fault == "lowbits":
            data = bytearray(Path(argv[3]).read_bytes()); data[0] |= 1
            Path(argv[3]).write_bytes(data)
        value = {"schema": "yblod.vaapi-scaler-invocation.v1", "status": "complete", "vendor": "synthetic fake",
                 "va_version": [1, 24], "input_size": [iw, ih], "output_size": [ow, oh], "filter_flags": 0,
                 "input_chroma_siting": None if copy else {"left": 6, "top-left": 5}[i],
                 "output_chroma_siting": None if copy else {"left": 6, "top-left": 5}[o],
                 "colour_standard": None if copy else 12, "colour_range": None if copy else 2,
                 "vpp_submitted": not copy, "hardware_engine_verified": False}
        if self.fault == "metadata": value["input_size"] = [float(iw), ih]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b"fake")

    def execute(self, name):
        with patch.object(large.subprocess, "run", side_effect=self.fake):
            return large.run(self.binary, self.root/name, 64, 64)

    def test_complete_order130_jobs_and_streamed_metrics(self):
        report = self.execute("complete")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(self.calls), 130)
        self.assertTrue(all(int(call[6]) == 64 for call in self.calls[:50]))
        self.assertTrue(all(int(call[6]) == 128 for call in self.calls[50:]))
        self.assertFalse(report["hardware_engine_verified"])
        self.assertIn("self_peak_rss_native", report["resources"])

    def test_last_same_grid_gate_lowbits_metadata_prevent_scaling(self):
        for fault in ("top-left-identity", "lowbits", "metadata"):
            self.fault, self.calls = fault, []
            report = self.execute(fault)
            self.assertEqual(report["status"], "failed", fault)
            self.assertTrue(all(int(call[6]) == 64 for call in self.calls))


if __name__ == "__main__": unittest.main()
