"""Audit saved query-control evidence, not GPU performance or VM execution."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
REPORT = HERE / "results" / "native-gpu-query-control-vm-20261005e.json"
PIN = "de72916aa477ad167b023ffc6475edf9fe005a645ff98f2e07bed3d3d6272539"
LIMIT = 1024 * 1024


def audit(raw):
    if type(raw) is not bytes or len(raw) > LIMIT:
        raise ValueError("bounded checkpoint bytes required")
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise ValueError("saved checkpoint changed")
    result = json.loads(raw)
    if (result["schema"] != "yblod.native-gpu-query-control-results.v1"
            or result["status"] != "diagnostic-complete"):
        raise ValueError("complete diagnostic evidence required")
    return result


class SavedQueryControlResultsTests(unittest.TestCase):
    def report(self):
        with REPORT.open("rb") as stream:
            return audit(stream.read(LIMIT + 1))

    def test_executed_source_and_binary_pins(self):
        result = self.report()
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        self.assertEqual(len(result["source_sha256"]), 20)
        for name, pin in result["source_sha256"].items():
            self.assertRegex(pin, r"^[0-9a-f]{64}$")
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), pin)
        self.assertEqual(result["binary_sha256"], {
            "device": "6d3f840d55dd5b662def02a489039a7f83f8519676037b1b9c9f9158f52c67ca",
            "control": "6bd10fa2e171e4bcc0e23d95a89d91040d29448005de781410dee1ea9120cb53"})

    def test_all_four_cohorts_exactness_and_resource_guards(self):
        result = self.report()
        self.assertEqual(result["run_order"], [
            "device-2296", "device-1406", "control-2296", "control-1406"])
        self.assertEqual([(c["backend"], c["label"]) for c in result["cohorts"]], [
            ("unbracketed-device-query", "prepared-frame-2296"),
            ("unbracketed-device-query", "prepared-frame-1406"),
            ("host-synchronized-query-control", "prepared-frame-2296"),
            ("host-synchronized-query-control", "prepared-frame-1406")])
        for c in result["cohorts"]:
            self.assertEqual(c["execution_status"], "complete")
            self.assertEqual(c["counts"], [8294400, 2073600, 2073600])
            self.assertEqual(c["gpu_verified_stage_values"], 49766400)
            self.assertEqual((c["gpu_verified_dispatches"], c["gpu_oracle_dispatches"]), (48, 191))
            self.assertEqual((c["gpu_batch_samples"], c["cpu_chunk_samples"]), (262144, 65536))
            self.assertEqual((c["golden_suffix_offset"], c["golden_suffix_samples"]), (196608, 41984))
            self.assertEqual(c["stage_mismatch_counts"], [0, 0, 0, 0])
            self.assertEqual(c["timer_counter_bits"], 64)
            self.assertEqual(c["device_query_counts"], [48, 48, 48])
            for key in ("cpu_full_frame_gate", "full_frame_gpu_exact",
                        "device_binding_verified", "cleanup_succeeded",
                        "kodi_active_before_and_after", "device_timer_attempted",
                        "executed_artifact_and_input_identities_unchanged"):
                self.assertIs(c[key], True)
            self.assertIs(c["whole_frame_resident"], False)
            self.assertIs(c["device_timing_is_alu_busy"], False)
            self.assertEqual(c["observed_gl_error"], 0)
            self.assertEqual(c["observed_egl_error"], 12288)
            self.assertEqual(c["memory_max_bytes"], 512 * 1024**2)
            self.assertLess(c["charged_peak_bytes"], c["memory_max_bytes"])
            for key in ("swap_bytes", "memory_limit_events", "oom_events", "oom_kill_events"):
                self.assertEqual(c[key], 0)
            for key in ("wall_ns", "cpu_ns", "dispatch_wall_ns", "dispatch_cpu_ns",
                        "preload_wait_wall_ns", "device_elapsed_ns"):
                self.assertEqual(len(c[key]), 3)
                self.assertTrue(all(type(v) is int and v > 0 for v in c[key]))
            for index in range(3):
                self.assertLessEqual(c["dispatch_cpu_ns"][index], c["cpu_ns"][index])
                self.assertLessEqual(c["dispatch_wall_ns"][index] +
                                     c["preload_wait_wall_ns"][index], c["wall_ns"][index])
                self.assertLessEqual(c["device_elapsed_ns"][index], 48 * 5000000000)
            self.assertEqual(c["warmups"], 1)

    def test_rejected_compute_evidence_and_source_inference_not_driver_proof(self):
        result = self.report()
        self.assertIs(result["compute_performance_validated"], False)
        for c in result["cohorts"][:2]:
            self.assertEqual(c["timer_evidence_status"],
                             "untrusted-not-accepted-for-compute-performance")
            self.assertLess(max(c["device_elapsed_ns"]), 1000000)
        for c in result["cohorts"][2:]:
            self.assertEqual(c["timer_evidence_status"],
                             "chronological-control-only-not-exclusive-compute-time")
            self.assertEqual(c["timer_method"], "host-synchronized-cross-batch-bracket")
        mesa = result["mesa_source_review"]
        self.assertEqual(mesa["version"], "26.2.4")
        self.assertIs(mesa["loaded_driver_identity_verified"], False)
        self.assertGreaterEqual(len(mesa["source_sha256"]), 3)
        for name, pin in mesa["source_sha256"].items():
            self.assertTrue(name.startswith("src/gallium/drivers/iris/"))
            self.assertRegex(pin, r"^[0-9a-f]{64}$")

    def test_changed_private_or_oversized_checkpoint_rejected(self):
        raw = REPORT.read_bytes()
        for altered in (raw + b" ", b"{", b"x" * (LIMIT + 1),
                        raw.replace(b'"compute_performance_validated": false',
                                    b'"compute_performance_validated": true')):
            with self.assertRaises(ValueError):
                audit(altered)
        result = json.loads(raw)
        result["private_pixels"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            audit(json.dumps(result).encode())


if __name__ == "__main__":
    unittest.main()
