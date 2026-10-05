"""Audit saved public ABBA evidence; no GPU, VM or private inputs."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
REPORT = HERE / "NLQ_LUT_ABBA_RESULTS.json"
PIN = "2bfdbbfc086dc5d07f46c6352064f8f8bb3e9ddeabfc7678bb195fa221e93503"
LIMIT = 1024 * 1024


def audit(raw):
    if type(raw) is not bytes or len(raw) > LIMIT:
        raise ValueError("bounded public evidence required")
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise ValueError("saved evidence changed")
    value = json.loads(raw)
    if value["schema"] != "yblod.nlq-lut-abba-results.v1":
        raise ValueError("ABBA evidence schema required")
    return value


class SavedNLQLUTABBAResultsTests(unittest.TestCase):
    def report(self):
        with REPORT.open("rb") as stream:
            return audit(stream.read(LIMIT + 1))

    def test_public_artifact_provenance(self):
        value = self.report()
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        pins = value["provenance"]["source_sha256"]
        self.assertEqual(len(pins), 21)
        for name, pin in pins.items():
            self.assertTrue(name.startswith("engine/"))
            self.assertRegex(pin, r"^[0-9a-f]{64}$")
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), pin)
        self.assertEqual(value["provenance"]["binary_sha256"], {
            "baseline": "8b37a01e5fc162fa9eb3290da5d86a65e610069d2bb7c55010cb7a98b5de132b",
            "lut": "08c02f14495ddac52442acdf23476a7ec76274a4a19f5ddb4cda815a80422c84"})

    def test_eight_cohort_geometry_exactness_and_timing_costs(self):
        runs = self.report()["runs"]
        self.assertEqual([r["label"] for r in runs], [
            "2296-1-baseline", "2296-2-lut", "2296-3-lut", "2296-4-baseline",
            "1406-1-baseline", "1406-2-lut", "1406-3-lut", "1406-4-baseline"])
        for run in runs:
            r = run["result"]
            self.assertEqual(r["status"], "complete")
            self.assertEqual(r["counts"], [8294400, 2073600, 2073600])
            self.assertEqual((r["cpu_dispatches"], r["gpu_oracle_dispatches"]), (191, 191))
            self.assertEqual((r["cpu_stage_values"], r["gpu_verified_stage_values"]), (49766400, 49766400))
            self.assertEqual((r["gpu_batch_dispatches"], r["gpu_verified_dispatches"]), (48, 48))
            self.assertEqual((r["gpu_batch_samples"], r["cpu_chunk_samples"]), (262144, 65536))
            self.assertEqual((r["golden_suffix_offset"], r["golden_suffix_samples"]), (196608, 41984))
            self.assertEqual(r["timed_crosscheck_scope"], "final-CPU-subchunk-suffix-only")
            for key in ("gpu_attempted", "cpu_full_frame_gate", "full_frame_gpu_exact",
                        "device_binding_verified", "cleanup_succeeded",
                        "preloaded_chunk_dispatch_measurement"):
                self.assertIs(r[key], True)
            self.assertIs(r["whole_frame_resident"], False)
            self.assertIs(r["dispatch_timing_is_device_kernel_time"], False)
            self.assertEqual((r["observed_gl_error"], r["observed_egl_error"]), (0, 12288))
            self.assertEqual(r["warmups"], 1)
            for key in ("wall_ns", "cpu_ns", "dispatch_wall_ns",
                        "dispatch_cpu_ns", "preload_wait_wall_ns"):
                self.assertEqual(len(r[key]), 3)
                self.assertTrue(all(type(n) is int and n > 0 for n in r[key]))
            for i in range(3):
                self.assertLessEqual(r["dispatch_cpu_ns"][i], r["cpu_ns"][i])
                self.assertLessEqual(r["dispatch_wall_ns"][i] + r["preload_wait_wall_ns"][i],
                                     r["wall_ns"][i])
            self.assertGreater(r["cold_setup_wall_ns"], 0)
            self.assertGreater(r["teardown_wall_ns"], 0)
            if run["variant"] == "lut":
                self.assertEqual((r["lut_entries"], r["lut_bytes"]), (3072, 12288))
                self.assertIs(r["lut_setup_in_warm_timing"], False)
                self.assertIs(r["lut_upload_in_cold_setup"], True)
                for key in ("lut_generation_wall_ns", "lut_generation_cpu_ns", "lut_upload_wall_ns"):
                    self.assertGreater(r[key], 0)
                self.assertLessEqual(r["lut_upload_wall_ns"], r["cold_setup_wall_ns"])

    def test_resources_and_no_performance_or_playback_claim(self):
        value = self.report()
        self.assertEqual(value["claims"], {
            "reference_equivalence_only": True, "production_playback_tested": False,
            "performance_gain_established": False, "device_kernel_time_measured": False})
        for run in value["runs"]:
            resource = run["resources"]
            for key in ("wrapper_unchanged", "files_and_runtime_unchanged"):
                self.assertIs(resource[key], True)
            self.assertEqual((resource["kodi_before"], resource["kodi_after"]), ("active", "active"))
            for phase in ("before", "after"):
                p = resource[phase]
                self.assertEqual(p["memory.max"], "536870912")
                self.assertEqual(p["memory.swap.max"], "0")
                self.assertEqual(p["memory.swap.current"], "0")
                self.assertLess(int(p["memory.peak"]), 512 * 1024**2)
                events = dict(line.split() for line in p["memory.events"].splitlines())
                for key in ("high", "max", "oom", "oom_kill", "oom_group_kill"):
                    self.assertEqual(events[key], "0")
                self.assertEqual(p["cpu.max"], "unavailable")

    def test_privacy_allowlist_and_tamper_rejection(self):
        value = self.report()
        self.assertEqual(set(value), {"schema", "provenance", "claims", "runs"})
        base = {"schema", "gpu_attempted", "cpu_full_frame_gate", "cpu_dispatches",
                "cpu_stage_values", "counts", "golden_suffix_offset", "cpu_chunk_samples",
                "timed_crosscheck_scope", "gpu_batch_samples", "gpu_batch_dispatches",
                "golden_suffix_samples", "renderer", "gl_version", "shader_log", "link_log",
                "device_binding_verified", "observed_gl_error", "observed_egl_error",
                "cleanup_succeeded", "full_frame_gpu_exact", "gpu_verified_dispatches",
                "gpu_oracle_dispatches", "gpu_verified_stage_values", "cold_setup_wall_ns",
                "teardown_wall_ns", "warmups", "wall_ns", "cpu_ns",
                "preloaded_chunk_dispatch_measurement", "whole_frame_resident",
                "dispatch_timing_is_device_kernel_time", "dispatch_timing_scope",
                "preload_wait_wall_ns", "dispatch_wall_ns", "dispatch_cpu_ns", "status"}
        extras = {"lut_entries", "lut_bytes", "lut_generation_wall_ns", "lut_generation_cpu_ns",
                  "lut_setup_in_warm_timing", "lut_upload_in_cold_setup", "lut_upload_wall_ns"}
        for run in value["runs"]:
            self.assertEqual(set(run), {"frame", "label", "variant", "result", "resources"})
            self.assertEqual(set(run["result"]), base | (extras if run["variant"] == "lut" else set()))
            self.assertEqual(run["result"]["shader_log"], "")
            self.assertEqual(run["result"]["link_log"], "")
        raw = REPORT.read_bytes()
        for altered in (raw + b" ", b"{", b"x" * (LIMIT + 1)):
            with self.assertRaises(ValueError):
                audit(altered)
        value["private_pixels"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            audit(json.dumps(value).encode())


if __name__ == "__main__":
    unittest.main()
