"""Verify a pinned public result; these tests never execute GPU work."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "results/native-gpu-scaled-frame-profile-libreelec-20261005a.json"
REPORT_SHA256 = "9cccbd0922c4e63202a18d782e98256bf16038c306d3538d0be9dab948bf9d18"


def load_pinned(path):
    with path.open("rb") as stream:
        payload = stream.read(1048577)
    if len(payload) > 1048576:
        raise ValueError("public report too large")
    if hashlib.sha256(payload).hexdigest() != REPORT_SHA256:
        raise ValueError("public report changed")
    return json.loads(payload)


class GPUScaledFrameProfileResultsTests(unittest.TestCase):
    def test_recorded_complete_gate_and_host_phase_accounting(self):
        report = load_pinned(REPORT)
        self.assertEqual(report["schema"],
                         "yblod.native-gpu-scaled-frame-profile-results.v1")
        self.assertEqual(report["status"], "complete")
        for flag in ("gpu_attempted", "cpu_full_frame_gate", "full_frame_gpu_exact",
                     "instrumented_gpu_path_profile", "cleanup_succeeded"):
            self.assertIs(report[flag], True)
        self.assertIs(report["dispatch_wait_is_device_kernel_time"], False)
        self.assertEqual(report["phase_clock"], "host-monotonic-wall")
        self.assertEqual(report["gpu_verified_dispatches"], 191)
        self.assertEqual(report["gpu_verified_stage_values"], 49766400)
        self.assertEqual(report["gpu_verified_stage_values"], 4 * sum(report["counts"]))
        self.assertEqual(report["timed_crosscheck_scope"], "last-chunk-only")
        phases = ("extract_pack_wall_ns", "upload_wall_ns",
                  "dispatch_barrier_fence_wait_wall_ns", "readback_wall_ns")
        for name in (*phases, "wall_ns", "cpu_ns"):
            self.assertEqual(len(report[name]), 3)
            self.assertTrue(all(type(n) is int and n >= 0 for n in report[name]))
        for index, total in enumerate(report["wall_ns"]):
            self.assertLessEqual(sum(report[name][index] for name in phases), total)
        resources = report["resources"]
        self.assertEqual(resources["memory_max_bytes"], 536870912)
        self.assertLess(resources["memory_peak_bytes"], resources["memory_max_bytes"])
        self.assertEqual(resources["memory_swap_max_bytes"], 0)
        self.assertEqual(resources["memory_swap_current_bytes"], 0)
        self.assertTrue(all(type(n) is int and n == 0
                            for n in resources["memory_events"].values()))

    def test_current_executed_source_pins(self):
        report = load_pinned(REPORT)
        repository = ROOT.parents[2]
        self.assertEqual(len(report["source_sha256"]), 19)
        for relative, expected in report["source_sha256"].items():
            self.assertFalse(Path(relative).is_absolute())
            self.assertNotIn("..", Path(relative).parts)
            with (repository / relative).open("rb") as stream:
                payload = stream.read(1048577)
            self.assertLessEqual(len(payload), 1048576)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected, relative)

    def test_modified_or_oversized_public_report_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            for payload in (b"{}", REPORT.read_bytes() + b" ", b"x" * 1048577):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    load_pinned(path)


if __name__ == "__main__":
    unittest.main()
