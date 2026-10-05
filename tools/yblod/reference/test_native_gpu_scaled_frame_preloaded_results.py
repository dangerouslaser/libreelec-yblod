"""Audit saved public preloaded timing evidence; no GPU or private inputs."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
REPORT = HERE / "results" / "native-gpu-scaled-frame-preloaded-vm-20261005c.json"
PIN = "92d01e1b0bf20636bd65bc986fd317e766952c424e16858e900ee7e4c13383b8"
LIMIT = 1024 * 1024


def audit(raw):
    if type(raw) is not bytes or len(raw) > LIMIT:
        raise ValueError("bounded checkpoint bytes required")
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise ValueError("saved checkpoint changed")
    result = json.loads(raw)
    if result["schema"] != "yblod.native-gpu-scaled-frame-preloaded-results.v1" or result["status"] != "complete":
        raise ValueError("complete public aggregate required")
    return result


class SavedPreloadedResultsTests(unittest.TestCase):
    def report(self):
        with REPORT.open("rb") as stream:
            return audit(stream.read(LIMIT + 1))

    def test_artifact_pins(self):
        result = self.report()
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        self.assertEqual(len(result["source_sha256"]), 19)
        for name, pin in result["source_sha256"].items():
            self.assertRegex(pin, r"^[0-9a-f]{64}$")
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), pin)
        self.assertEqual(result["binary_sha256"],
                         "8b37a01e5fc162fa9eb3290da5d86a65e610069d2bb7c55010cb7a98b5de132b")

    def test_all_values_timing_scope_and_resources(self):
        result = self.report()
        self.assertEqual([c["label"] for c in result["cohorts"]],
                         ["prepared-frame-2296", "prepared-frame-1406"])
        self.assertIn("change the workload", result["comparison_policy"])
        for c in result["cohorts"]:
            self.assertEqual(c["counts"], [8294400, 2073600, 2073600])
            self.assertEqual(c["gpu_verified_stage_values"], 49766400)
            self.assertEqual((c["gpu_verified_dispatches"], c["gpu_oracle_dispatches"]), (48, 191))
            self.assertEqual((c["gpu_batch_samples"], c["cpu_chunk_samples"]), (262144, 65536))
            self.assertEqual((c["golden_suffix_offset"], c["golden_suffix_samples"]), (196608, 41984))
            self.assertEqual(c["stage_mismatch_counts"], [0, 0, 0, 0])
            for key in ("cpu_full_frame_gate", "full_frame_gpu_exact",
                        "device_binding_verified", "cleanup_succeeded",
                        "kodi_active_before_and_after",
                        "executed_artifact_and_input_identities_unchanged",
                        "preloaded_chunk_dispatch_measurement"):
                self.assertIs(c[key], True)
            self.assertIs(c["whole_frame_resident"], False)
            self.assertIs(c["dispatch_timing_is_device_kernel_time"], False)
            self.assertEqual(c["observed_gl_error"], 0)
            self.assertEqual(c["observed_egl_error"], 12288)
            self.assertEqual(c["memory_max_bytes"], 512 * 1024**2)
            self.assertLess(c["charged_peak_bytes"], c["memory_max_bytes"])
            for key in ("swap_bytes", "memory_limit_events", "oom_events", "oom_kill_events"):
                self.assertEqual(c[key], 0)
            for key in ("wall_ns", "cpu_ns", "dispatch_wall_ns",
                        "dispatch_cpu_ns", "preload_wait_wall_ns"):
                self.assertEqual(len(c[key]), 3)
                self.assertTrue(all(type(v) is int and v > 0 for v in c[key]))
            for index in range(3):
                self.assertLessEqual(c["dispatch_cpu_ns"][index], c["cpu_ns"][index])
                self.assertLessEqual(c["dispatch_wall_ns"][index] +
                                     c["preload_wait_wall_ns"][index], c["wall_ns"][index])
            for key in ("cold_setup_wall_ns", "teardown_wall_ns"):
                self.assertGreater(c[key], 0)
            self.assertEqual(c["warmups"], 1)

    def test_mutated_private_or_oversized_checkpoint_rejected(self):
        raw = REPORT.read_bytes()
        for altered in (raw + b" ", b"{", b"x" * (LIMIT + 1),
                        raw.replace(b'"status": "complete"', b'"status": "failed"')):
            with self.assertRaises(ValueError):
                audit(altered)
        value = json.loads(raw)
        value["private_pixels"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            audit(json.dumps(value).encode())


if __name__ == "__main__":
    unittest.main()

