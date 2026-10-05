"""Audit saved GPU batching evidence; no GPU/VM execution or private inputs."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
REPORT = HERE / "results" / "native-gpu-scaled-frame-batch-vm-20261005b.json"
PIN = "48843f98aadcc9a8a29025e98e56c6459f8a03eb159cef51e481b7d4c32ac54c"
LIMIT = 1024 * 1024


def audit(raw):
    if type(raw) is not bytes or len(raw) > LIMIT:
        raise ValueError("bounded checkpoint bytes required")
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise ValueError("saved checkpoint changed")
    value = json.loads(raw)
    if value["schema"] != "yblod.native-gpu-scaled-frame-batch-results.v1" or value["status"] != "complete":
        raise ValueError("complete aggregate required")
    return value


class SavedBatchResultsTests(unittest.TestCase):
    def report(self):
        with REPORT.open("rb") as stream:
            return audit(stream.read(LIMIT + 1))

    def test_source_and_binary_pins(self):
        value = self.report()
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        self.assertEqual(len(value["source_sha256"]), 20)
        for name, pin in value["source_sha256"].items():
            self.assertRegex(pin, r"^[0-9a-f]{64}$")
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), pin)
        self.assertEqual(value["binary_sha256"], {
            "baseline": "98bec09c49a8d0b25fbed1122035a3a61b62bb15a31f672df2854de3c8037b67",
            "batch": "aa1eedeaeed371335dc68893ccddf68986cfb41e4cde7f278687b626cf6b9cef"})

    def test_all_four_cohorts_and_resource_guards(self):
        value = self.report()
        self.assertEqual(value["run_order"], [
            "baseline-2296", "batch-2296", "batch-1406", "baseline-1406"])
        self.assertEqual([(c["label"], c["backend"]) for c in value["cohorts"]], [
            ("prepared-frame-2296", "baseline-65536"),
            ("prepared-frame-2296", "batch-262144"),
            ("prepared-frame-1406", "batch-262144"),
            ("prepared-frame-1406", "baseline-65536")])
        for c in value["cohorts"]:
            self.assertEqual(c["counts"], [8294400, 2073600, 2073600])
            self.assertEqual(c["cpu_chunk_samples"], 65536)
            self.assertEqual(c["cpu_oracle_dispatches"], 191)
            self.assertEqual(c["gpu_verified_stage_values"], 49766400)
            self.assertEqual(c["stage_mismatch_counts"], [0, 0, 0, 0])
            batch = c["backend"] == "batch-262144"
            self.assertEqual(c["gpu_verified_dispatches"], 48 if batch else 191)
            self.assertEqual(c["gpu_batch_samples"], 262144 if batch else 65536)
            if batch:
                self.assertEqual((c["golden_suffix_offset"], c["golden_suffix_samples"]),
                                 (196608, 41984))
            for key in ("cpu_full_frame_gate", "full_frame_gpu_exact",
                        "device_binding_verified", "cleanup_succeeded",
                        "kodi_active_before_and_after",
                        "executed_artifact_and_input_identities_unchanged"):
                self.assertIs(c[key], True)
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

    def test_explicit_nonpaired_scope_and_tamper_rejection(self):
        value = self.report()
        self.assertIn("not interleaved paired", value["comparison_design"])
        self.assertIn("suffix", value["timed_crosscheck_scope"]["batch"])
        raw = REPORT.read_bytes()
        for altered in (raw + b" ", b"{", b"x" * (LIMIT + 1),
                        raw.replace(b'"status": "complete"', b'"status": "failed"')):
            with self.assertRaises(ValueError):
                audit(altered)
        value["private_pixels"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            audit(json.dumps(value).encode())


if __name__ == "__main__":
    unittest.main()

