"""Audit a saved public checkpoint; no VM, GPU or private input access."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
REPORT = HERE / "results" / "native-gpu-scaled-frame-vm-20261005a.json"
PIN = "38b9c8cbb14968e63a8d505b105800b4cd8ecfbc20438508effc37c1c100b204"
LIMIT = 1024 * 1024


def audit(raw):
    if type(raw) is not bytes or len(raw) > LIMIT:
        raise ValueError("bounded public checkpoint bytes required")
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise ValueError("saved checkpoint changed")
    result = json.loads(raw)
    if result["schema"] != "yblod.native-gpu-scaled-frame-results.v1" or result["status"] != "complete":
        raise ValueError("complete saved aggregate required")
    return result


class SavedGPUFrameResultsTests(unittest.TestCase):
    def load_report(self):
        with REPORT.open("rb") as stream:
            return audit(stream.read(LIMIT + 1))

    def test_exact_saved_report_and_sources(self):
        result = self.load_report()
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        self.assertEqual(len(result["source_sha256"]), 19)
        for name, expected in result["source_sha256"].items():
            self.assertRegex(expected, r"^[0-9a-f]{64}$")
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(result["binary_sha256"], "98bec09c49a8d0b25fbed1122035a3a61b62bb15a31f672df2854de3c8037b67")

    def test_complete_two_cohort_evidence(self):
        result = self.load_report()
        self.assertEqual([c["label"] for c in result["cohorts"]],
                         ["prepared-frame-2296", "prepared-frame-1406"])
        for c in result["cohorts"]:
            self.assertEqual(c["counts"], [8294400, 2073600, 2073600])
            self.assertEqual(c["gpu_verified_dispatches"], 191)
            self.assertEqual(c["gpu_verified_stage_values"], 49766400)
            self.assertEqual(c["stage_mismatch_counts"], [0, 0, 0, 0])
            for flag in ("cpu_full_frame_gate", "full_frame_gpu_exact",
                         "device_binding_verified", "cleanup_succeeded",
                         "kodi_active_before_and_after"):
                self.assertIs(c[flag], True)
            self.assertEqual(c["observed_gl_error"], 0)
            self.assertEqual(c["observed_egl_error"], 12288)
            self.assertEqual(c["memory_max_bytes"], 512 * 1024**2)
            self.assertLess(c["charged_peak_bytes"], c["memory_max_bytes"])
            for key in ("swap_bytes", "memory_limit_events", "oom_events", "oom_kill_events"):
                self.assertEqual(c[key], 0)
            for key in ("wall_ns", "cpu_ns"):
                self.assertEqual(len(c[key]), 3)
                self.assertTrue(all(type(v) is int and v > 0 for v in c[key]))
            for key in ("cold_setup_wall_ns", "teardown_wall_ns"):
                self.assertGreater(c[key], 0)
            self.assertEqual(c["warmups"], 1)

    def test_changed_private_or_oversized_evidence_rejected(self):
        raw = REPORT.read_bytes()
        for altered in (raw + b" ", b"{", b"x" * (LIMIT + 1),
                        raw.replace(b'"status": "complete"', b'"status": "failed"')):
            with self.assertRaises(ValueError):
                audit(altered)
        result = json.loads(raw)
        result["private_pixels"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            audit(json.dumps(result).encode())


if __name__ == "__main__":
    unittest.main()
