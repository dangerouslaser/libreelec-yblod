"""Synthetic fake subprocesses only; no GPU or movie frames."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_chroma_siting_check as checker
from scaling_probe import CHANNELS, pack_p010, unpack_p010


class HardwareChromaSitingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root/"fake"
        self.binary.write_bytes(b"fake hardware, not device results")
        self.calls, self.fault = [], None

    def fake(self, argv, **kwargs):
        self.assertEqual(kwargs, {"capture_output": True, "timeout": 30, "check": False})
        self.calls.append(argv)
        size = int(argv[6])
        copy = argv[8] == "copy"
        i, o = ("left", "left") if copy else (argv[10], argv[12])
        inputs = unpack_p010(Path(argv[2]).read_bytes(), 64, 64)
        output = {c: [[inputs[c][y//(size//64)][x//(size//64)]
                       for x in range(size if c == "Y" else size//2)]
                      for y in range(size if c == "Y" else size//2)] for c in CHANNELS}
        affine = "neutral" not in argv[2] and "channel-tags" not in argv[2]
        if not copy and i != o and affine:
            for c in ("Cb", "Cr"):
                output[c] = [[v+1 for v in row] for row in output[c]]
        if self.fault == "luma" and not copy and i != o and affine: output["Y"][0][0] += 1
        if self.fault == "copy-identity" and copy: output["Y"][0][0] += 1
        if self.fault == "constant" and not copy and not affine: output["Cb"][0][0] += 1
        if self.fault == "same-grid" and not copy and i == o and affine: output["Cb"][0][0] += 1
        if self.fault == "top-left-identity" and not copy and i == o == "top-left" and size == 64 and affine:
            output["Cb"][0][0] += 1
        if self.fault == "unstable" and argv[3].endswith("-1.p010"): output["Cr"][0][0] += 1
        data = pack_p010(output)
        if self.fault == "lowbits": data = bytes([data[0]|1])+data[1:]
        Path(argv[3]).write_bytes(data)
        value = {"schema": "yblod.vaapi-scaler-invocation.v1", "status": "complete",
                 "vendor": "synthetic fake", "va_version": [1, 24],
                 "input_size": [64, 64], "output_size": [size, size], "filter_flags": 0,
                 "input_chroma_siting": None if copy else checker.SITING[i],
                 "output_chroma_siting": None if copy else checker.SITING[o],
                 "colour_standard": None if copy else 12, "colour_range": None if copy else 2,
                 "vpp_submitted": not copy, "hardware_engine_verified": False}
        if self.fault == "metadata" and not copy: value["input_chroma_siting"] = 0
        if self.fault == "timeout": raise subprocess.TimeoutExpired(argv, 30, output=b"partial")
        return subprocess.CompletedProcess(argv, 1 if self.fault == "nonzero" else 0,
                                           json.dumps(value).encode(), b"fake diagnostics")

    def execute(self, name="run"):
        with patch.object(checker.subprocess, "run", side_effect=self.fake):
            report = checker.run(self.binary, self.root/name)
        self.assertEqual(report, json.loads((self.root/name/"chroma-siting-report.json").read_text()))
        return report

    def test_matrix_all_four_settings_and_cross_grid_difference_allowed(self):
        report = self.execute()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(self.calls), 102)
        self.assertTrue(all(int(call[6]) == 64 for call in self.calls[:54]))
        self.assertTrue(all(int(call[6]) == 128 for call in self.calls[54:]))
        self.assertEqual(len(report["results"]), 4)
        cross = report["results"]["left-to-top-left"]["64"]["x"]
        self.assertFalse(cross["identity"]["exact"])
        self.assertTrue(cross["luma_identical_across_siting_requests"])
        self.assertEqual(cross["differences_from_left_to_left"]["Cb"]["error_values"], [1])
        self.assertIn("affine_first_moment", report["results"]["top-left-to-top-left"]["128"]["y-desc"])

    def test_same_grid_identity_and_constant_and_luma_are_gates(self):
        for fault in ("same-grid", "constant", "luma"):
            self.fault, self.calls = fault, []
            report = self.execute(fault)
            self.assertEqual(report["status"], "failed")
            self.assertLess(len(self.calls), 102)
            self.assertTrue(report["copy_checks_complete"])

    def test_unstable_metadata_lowbits_exit_and_timeout_fail_closed(self):
        for fault in ("unstable", "metadata", "lowbits", "nonzero", "timeout"):
            self.fault, self.calls = fault, []
            report = self.execute(fault)
            self.assertEqual(report["status"], "failed", fault)
            self.assertIn("stdout", report["invocations"][-1])
            self.assertIn("stderr", report["invocations"][-1])

    def test_copy_identity_blocks_every_vpp_request(self):
        self.fault = "copy-identity"
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][8], "copy")
        self.assertFalse(report["invocations"][0]["identity"]["exact"])

    def test_last_same_grid_identity_failure_blocks_every_2x_request(self):
        self.fault = "top-left-identity"
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["copy_checks_complete"])
        self.assertTrue(all(int(call[6]) == 64 for call in self.calls))
        failed = report["results"]["top-left-to-top-left"]["64"]["x"]
        self.assertFalse(failed["identity"]["exact"])
        self.assertTrue(all("128" not in config for config in report["results"].values()))

    def test_invalid_repeat_and_fresh_output_requirements(self):
        with patch.object(checker.subprocess, "run", side_effect=self.fake):
            report = checker.run(self.binary, self.root/"invalid", repeats=1)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(self.calls, [])
            with self.assertRaises(FileExistsError): checker.run(self.binary, self.root/"invalid")


if __name__ == "__main__":
    unittest.main()
