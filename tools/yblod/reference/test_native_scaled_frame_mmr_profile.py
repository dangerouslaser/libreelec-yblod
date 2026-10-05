"""Instrumented diagnostic guards; no real-frame performance claim."""
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
import test_native_scaled_frame_mmr_benchmark as base

ROOT = Path(__file__).resolve().parent


class MMRProfileTests(base.MMRBenchmarkTests):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "mmr-profile"
        subprocess.run([
            "cc", "-std=c11", "-O2", "-fno-lto", "-Wall", "-Wextra",
            "-Werror", "-Wconversion", "-Wshadow",
            *shlex.split(os.environ.get("YB_CACHED_BENCHMARK_TEST_CFLAGS", "")),
            *(str(ROOT / name) for name in (
                "native_scaled_frame_mmr_profile.c", "native_mmr_composer.c",
                "native_scaled_surface.c", "native_decoder_frame_bridge.c",
                "native_integration_probe.c", "native_composer.c",
                "native_sampling_probe.c")),
            "-o", str(cls.binary)], check=True, capture_output=True)

    def test_component_timer_accounting(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            result = self.invoke(paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["instrumented_component_wall_profile"])
            self.assertEqual(report["component_order"], ["Y", "Cb", "Cr"])
            for backend in ("reference", "mmr"):
                data = report[backend]
                for repeat in range(3):
                    measured = data["preparation_wall_ns"][repeat]
                    for c in range(3):
                        for stage in ("extraction", "reconstruction"):
                            values = data[f"{stage}_component_{c}_wall_ns"]
                            self.assertEqual(len(values), 3)
                            self.assertTrue(all(type(v) is int and v >= 0 for v in values))
                            measured += values[repeat]
                    self.assertLessEqual(measured, data["wall_ns"][repeat])
