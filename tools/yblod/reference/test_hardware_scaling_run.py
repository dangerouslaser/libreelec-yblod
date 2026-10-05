"""Fake local subprocesses exercise fail-closed gating; never touch a GPU."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_scaling_run as runner
import hardware_scaling_vectors as vectors
import scaling_oracle
from scaling_probe import CHANNELS, pack_p010, unpack_p010


class HardwareScalingRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root/"fake-binary"
        self.binary.write_bytes(b"synthetic-test-binary")
        self.bundle = self.root/"bundle"
        vectors.generate(self.bundle, 4, 4)
        self.calls = []
        self.fault = None

    def fake(self, argv, **kwargs):
        self.assertEqual(kwargs, {"capture_output": True, "timeout": 30, "check": False})
        self.calls.append(argv)
        iw, ih, ow, oh = map(int, argv[4:8])
        mode = argv[8]
        planes = unpack_p010(Path(argv[2]).read_bytes(), iw, ih)
        if (iw, ih) != (ow, oh):
            planes = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
            # Explicit fake P010's declared-depth bound for stress cases.
            # The scorer must retain the u16 expected overshoot and mismatch.
            planes = {c: [[min(v, 1023) for v in row] for row in planes[c]] for c in CHANNELS}
        copy = mode == "copy"
        invocation = {"schema": "yblod.vaapi-scaler-invocation.v1", "status": "complete",
                      "vendor": "synthetic fake, NOT hardware", "va_version": [1, 22],
                      "input_size": [iw, ih], "output_size": [ow, oh],
                      "filter_flags": 0 if copy else runner.FLAGS[mode],
                      "input_chroma_siting": None if copy else 6,
                      "output_chroma_siting": None if copy else 6,
                      "colour_standard": None if copy else 12,
                      "colour_range": None if copy else 2,
                      "vpp_submitted": not copy, "hardware_engine_verified": False}
        data = pack_p010(planes)
        if self.fault == "identity":
            planes["Y"][0][0] = (planes["Y"][0][0]+1)%1024
            data = pack_p010(planes)
        elif self.fault == "lowbits":
            data = bytes([data[0] | 1])+data[1:]
        elif self.fault == "metadata": invocation["vpp_submitted"] = copy
        elif self.fault == "flags": invocation["filter_flags"] = 1
        elif self.fault == "false-vpp" and not copy: invocation["vpp_submitted"] = False
        elif self.fault == "unstable" and "scale-" in argv[3] and argv[3].endswith("-1.p010"):
            planes["Y"][0][0] = (planes["Y"][0][0]+1)%1024
            data = pack_p010(planes)
        if self.fault != "missing": Path(argv[3]).write_bytes(data)
        if self.fault == "timeout":
            raise subprocess.TimeoutExpired(argv, 30, output=b"partial", stderr=b"timeout")
        return subprocess.CompletedProcess(argv, 1 if self.fault == "nonzero" else 0,
                                           json.dumps(invocation).encode(), b"synthetic stderr\n")

    def execute(self, name="run"):
        with patch.object(runner.subprocess, "run", side_effect=self.fake):
            result = runner.run(self.binary, self.bundle, self.root/name, modes=("default",), repeats=2)
        self.assertEqual(json.loads((self.root/name/"run-report.json").read_text()), result)
        return result

    def test_complete_requires_copy_and_vpp_identity_before_scaling(self):
        report = self.execute()
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["hardware_engine_verified"])
        self.assertEqual(len(self.calls), 56)
        self.assertTrue(all(a[4:6] == a[6:8] for a in self.calls[:28]))
        self.assertTrue(all(a[4:6] != a[6:8] for a in self.calls[28:]))
        stress = report["scaling"]["default"]["depth-overshoot"]
        self.assertTrue(stress["repeat_stable"])
        self.assertGreater(stress["expected_above_10bit_count"], 0)
        self.assertFalse(stress["exact"])

    def test_identity_failure_prevents_scaling(self):
        self.fault = "identity"
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(report["invocations"][0]["identity"]["exact"])

    def test_false_vpp_declaration_blocks_after_all_copy_checks(self):
        self.fault = "false-vpp"
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(self.calls), 15)
        self.assertEqual(report["invocations"][-1]["stage"], "identity-vpp")

    def test_three_modes_reuse_scores_not_invocation_records(self):
        with patch.object(runner.subprocess, "run", side_effect=self.fake), \
                patch.object(vectors, "score_scaled", wraps=vectors.score_scaled) as scorer:
            report = runner.run(self.binary, self.bundle, self.root/"three")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(self.calls), 112)
        self.assertEqual(scorer.call_count, 14)
        self.assertIsNot(report["scaling"]["default"]["zero"], report["scaling"]["fast"]["zero"])
        self.assertIn("self_peak_rss_native", report["resources"])
        self.assertIn("children_swap_delta", report["resources"])

    def test_failure_modes_retain_evidence(self):
        for fault in ("metadata", "flags", "lowbits", "nonzero", "missing", "timeout"):
            self.fault = fault
            self.calls.clear()
            report = self.execute(fault)
            self.assertEqual(report["status"], "failed", fault)
            self.assertEqual(len(self.calls), 1, fault)
            self.assertIn("stdout", report["invocations"][0])
            self.assertTrue((self.root/fault/report["invocations"][0]["stderr"]["file"]).exists())

    def test_tampered_input_pin_and_missing_input_never_invoke(self):
        original = (self.bundle/"hardware-probes.json").read_bytes()
        input_path = self.bundle/"zero-input.p010"
        data = input_path.read_bytes()
        input_path.write_bytes(b"bad")
        self.assertEqual(self.execute("tampered")["status"], "failed")
        self.assertEqual(self.calls, [])
        input_path.write_bytes(data)
        manifest = json.loads(original)
        manifest["oracle_sha256"] = "0"*64
        (self.bundle/"hardware-probes.json").write_text(json.dumps(manifest))
        self.assertEqual(self.execute("pin")["status"], "failed")
        self.assertEqual(self.calls, [])
        (self.bundle/"hardware-probes.json").write_bytes(original)
        input_path.unlink()
        self.assertEqual(self.execute("missing-input")["status"], "failed")
        self.assertEqual(self.calls, [])

    def test_repeat_instability_is_failed(self):
        self.fault = "unstable"
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(self.calls), 30)
        self.assertFalse(report["scaling"]["default"]["zero"]["repeat_stable"])

    def test_invalid_options_are_failed_without_gpu_and_fresh_directory_required(self):
        with patch.object(runner.subprocess, "run", side_effect=self.fake):
            result = runner.run(self.binary, self.bundle, self.root/"bad-options", modes=("bad",))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(self.calls, [])
            with self.assertRaises(FileExistsError):
                runner.run(self.binary, self.bundle, self.root/"bad-options")
            for index, modes in enumerate(("default", (), ("default", "default"), (0.5,))):
                result = runner.run(self.binary, self.bundle, self.root/f"options-{index}", modes=modes)
                self.assertEqual(result["status"], "failed")
            self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
