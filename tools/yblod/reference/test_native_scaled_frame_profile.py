"""Independent profiling-only timing schema/count guards; no playback claims."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import test_native_scaled_frame_benchmark as baseline

ROOT = Path(__file__).resolve().parent


class ProfilingTests(baseline.BenchmarkTests):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "profile"
        subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wconversion", "-Wshadow", *(str(ROOT / name) for name in
            ("native_scaled_frame_profile.c", "native_scaled_surface.c",
             "native_decoder_frame_bridge.c", "native_integration_probe.c",
             "native_composer.c", "native_sampling_probe.c")), "-o", str(cls.binary)],
            check=True, capture_output=True)

    def check_profile(self, result, counts, calls):
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "yblod.native-scaled-frame-profile.v1")
        self.assertEqual(report["counts"], counts)
        self.assertEqual(report["chunk_calls_per_run"], calls)
        self.assertIs(report["diagnostic_only"], True)
        self.assertIs(report["baseline_modified"], False)
        self.assertIs(report["all_frame_completions_verified"], True)
        self.assertIs(report["stage_sum_equals_end_to_end_claim"], False)
        self.assertEqual(report["clock_wall"], "CLOCK_MONOTONIC")
        self.assertEqual(report["clock_cpu"], "CLOCK_PROCESS_CPUTIME_ID")
        for key in ("nanoseconds", "process_cpu_nanoseconds", "initialization_wall_ns",
                    "initialization_cpu_ns", "completion_wall_ns", "completion_cpu_ns"):
            self.assertEqual(len(report[key]), 3)
            self.assertTrue(all(type(n) is int and n >= 0 for n in report[key]))
        for key in ("extraction_wall_ns_by_run_component", "extraction_cpu_ns_by_run_component",
                    "reconstruction_wall_ns_by_run_component", "reconstruction_cpu_ns_by_run_component"):
            self.assertEqual(len(report[key]), 3)
            for row in report[key]:
                self.assertEqual(len(row), 3)
                self.assertTrue(all(type(n) is int and n >= 0 for n in row))
        # No assertion that CPU/wall clocks have identical timing, or that
        # instrumented stage sums equal a separate end-to-end measurement.
        return report

    def test_profile_schema_and_both_clock_scopes(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            self.check_profile(self.invoke(paths), [4, 1, 1], [1, 1, 1])

    def test_full_sequential_multi_chunk_and_partial_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths, _ = self.fixture(directory)
            width, height = 514, 258
            ycount = width * height
            ccount = ycount // 4
            for path, count in zip(paths[1:5], (ycount, ccount, ccount, ccount)):
                with path.open("wb") as stream:
                    stream.write(struct.pack("<H", 512) * count)
            with paths[5].open("wb") as stream:
                stream.write(struct.pack("<H", 512 * 64) * (ycount + 2 * ccount))
            self.check_profile(self.invoke(paths, (str(width), str(height))),
                               [ycount, ccount, ccount], [3, 1, 1])

    def test_retained_public_checkpoint_replay_and_source_inventory(self):
        # Replay of published aggregate facts, NOT another real-frame C run.
        path = ROOT / "results" / "native-scaled-frame-profile-libreelec-20261005a.json"
        with path.open("rb") as stream:
            raw = stream.read(1048577)
        self.assertLessEqual(len(raw), 1048576)
        checkpoint = json.loads(raw)
        self.assertEqual(checkpoint["schema"], "yblod.native-scaled-frame-profile-checkpoint.v1")
        self.assertEqual(checkpoint["status"], "complete")
        self.assertIs(checkpoint["aggregate_only"], True)
        self.assertEqual(checkpoint["privacy"], {
            "film_pixels_published": False, "film_metadata_published": False,
            "private_input_hashes_published": False, "private_paths_published": False})
        measurement = checkpoint["measurement"]
        self.check_profile(type("Result", (), {
            "returncode": 0, "stderr": "", "stdout": json.dumps(measurement)})(),
            [8294400, 2073600, 2073600], [127, 32, 32])
        self.assertEqual(measurement["nanoseconds"], [651622655, 592168530, 600457509])
        self.assertEqual(measurement["process_cpu_nanoseconds"], [646078521, 591270858, 600283422])
        resources = checkpoint["resources"]
        self.assertEqual(resources["memory_max_bytes"], 536870912)
        self.assertEqual(resources["in_script_memory_peak_after_bytes"], 56848384)
        self.assertEqual(resources["memory_events_before"], {"max": 0, "oom": 0, "oom_kill": 0})
        self.assertEqual(resources["memory_events_after"], resources["memory_events_before"])
        for key in ("memory_swap_max_bytes", "memory_swap_current_before_bytes",
                    "memory_swap_current_after_bytes"):
            self.assertEqual(resources[key], 0)
        for name, expected in checkpoint["source_sha256"].items():
            self.assertEqual(Path(name).name, name)
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((ROOT / "native_scaled_frame_benchmark.c").read_bytes()).hexdigest(),
            "128cda86049a317f1e70cdd6f9cbbec0dfcb4dc0ec4047a83a5d6a2c09ff1656")


if __name__ == "__main__":
    unittest.main()
