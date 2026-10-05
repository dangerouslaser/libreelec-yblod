"""Synthetic host-only full-frame guards; no hardware execution or speed claim."""
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import unittest

import test_native_scaled_frame_benchmark as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFrameHostTests(base.BenchmarkTests):
    source_name = "native_gpu_scaled_frame_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-probe.v1"
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "gpu-scaled-frame-host"
        subprocess.run(["cc", "-std=c11", "-O2", "-fno-lto", "-Wall",
            "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            "-DYB_GPU_PROBE_HOST_ONLY",
            *shlex.split(os.environ.get("YB_GPU_FRAME_TEST_CFLAGS", "")),
            *(str(ROOT / name) for name in (
                cls.source_name, "native_gpu_guard.c",
                "native_gpu_probe_fixture.c",
                "native_mmr_composer.c", "native_scaled_surface.c",
                "native_decoder_frame_bridge.c", "native_integration_probe.c",
                "native_composer.c", "native_sampling_probe.c")),
            "-o", str(cls.binary)], check=True, capture_output=True)

    def invoke(self, paths, dimensions=("2", "2"), node="--validate"):
        # An absent shader is intentional: CPU validation must not load it.
        return subprocess.run([str(self.binary), node,
            str(Path(self.directory.name) / "ABSENT-SHADER.comp"),
            *dimensions, *(str(path) for path in paths)],
            capture_output=True, text=True, timeout=10)

    def rejected(self, result):
        self.assertNotEqual(result.returncode, 0)
        if result.stdout:
            report = json.loads(result.stdout)
            self.assertFalse(report.get("gpu_attempted", False))
            self.assertNotEqual(report.get("status"), "complete")
            self.assertFalse(report.get("full_frame_gpu_exact", False))

    def validated(self, result, counts, dispatches):
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], self.report_schema)
        self.assertEqual(report["status"], "validated")
        self.assertIs(report["gpu_attempted"], False)
        self.assertIs(report["cpu_full_frame_gate"], True)
        self.assertIs(report["full_frame_gpu_exact"], False)
        self.assertEqual(report["counts"], counts)
        self.assertEqual(report["cpu_dispatches"], dispatches)
        self.assertEqual(report["cpu_stage_values"], 4 * sum(counts))
        self.assertEqual(report["gpu_verified_dispatches"], 0)
        self.assertEqual(report["gpu_verified_stage_values"], 0)
        # No picture arrays or normalized Dolby coefficients in a public report.
        for field in ("mapped", "residual", "sum", "reconstructed", "coefficients"):
            self.assertNotIn(field, report)
        return report

    def test_successful_warmup_three_complete_passes(self):
        # Override the parent's CPU benchmark timing test: this mode has no GPU.
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            self.validated(self.invoke(paths), [4, 1, 1], 3)

    def test_mmr_all_orders(self):
        for order in (1, 2, 3):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as temporary:
                paths, instructions = self.fixture(Path(temporary))
                for component in (1, 2):
                    segment = instructions.mapping.components[component].segments[0]
                    segment.method = 1
                    segment.order = order
                    for row in range(3):
                        for term in range(7):
                            segment.coefficients[row][term] = 0
                    segment.coefficients[0][component] = 1 << 23
                    segment.coefficients[order - 1][6] = -(1 << 22)
                paths[0].write_bytes(bytes(instructions))
                self.validated(self.invoke(paths), [4, 1, 1], 3)

    def test_invalid_nlq_denominator_is_not_width_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, instructions = self.fixture(Path(temporary))
            instructions.nlq[2].denominator = 22
            paths[0].write_bytes(bytes(instructions))
            result = self.invoke(paths)
            self.rejected(result)
            self.assertNotEqual(result.returncode, 3)

    def test_valid_wide_mmr_explicitly_unsupported_before_gpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, instructions = self.fixture(Path(temporary))
            # The native coefficient envelope depends on the denominator.
            # D=32 admits this wide constant; D=23 would be malformed first.
            instructions.mapping.denominator = 32
            for nlq in instructions.nlq:
                nlq.denominator = 32
            segment = instructions.mapping.components[1].segments[0]
            segment.method = 1
            segment.order = 1
            for row in range(3):
                for term in range(7):
                    segment.coefficients[row][term] = 0
            segment.constant = 1 << 43
            paths[0].write_bytes(bytes(instructions))
            result = self.invoke(paths)
            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "unsupported")
            self.assertIs(report["gpu_attempted"], False)
            self.assertIs(report["full_frame_gpu_exact"], False)
            self.assertEqual(report["gpu_verified_dispatches"], 0)

    def test_wide_metadata_never_masks_malformed_late_inputs(self):
        for fault in ("nlq_denominator", "fractional_p010"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                paths, instructions = self.fixture(Path(temporary))
                instructions.mapping.denominator = 32
                for nlq in instructions.nlq:
                    nlq.denominator = 32
                segment = instructions.mapping.components[1].segments[0]
                segment.method = 1
                segment.order = 1
                for row in range(3):
                    for term in range(7):
                        segment.coefficients[row][term] = 0
                segment.constant = 1 << 43
                if fault == "nlq_denominator":
                    instructions.nlq[2].denominator = 31
                else:
                    raw = bytearray(paths[5].read_bytes())
                    raw[-2] |= 1
                    paths[5].write_bytes(raw)
                paths[0].write_bytes(bytes(instructions))
                result = self.invoke(paths)
                self.rejected(result)
                self.assertNotEqual(result.returncode, 3)
                if result.stdout:
                    self.assertNotEqual(json.loads(result.stdout)["status"], "unsupported")

    def test_multichunk_65536_boundary_partial_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            width, height = 258, 258
            ycount = width * height
            ccount = ycount // 4
            y = [(i * 17) % 1024 for i in range(ycount)]
            chroma = [(i * 19) % 1024 for i in range(ccount)]
            payloads = {
                1: struct.pack("<" + str(ycount) + "H", *y),
                2: struct.pack("<" + str(ccount) + "H", *chroma),
                3: struct.pack("<" + str(ccount) + "H", *reversed(chroma)),
                4: struct.pack("<" + str(ccount) + "H", *chroma),
                5: struct.pack("<" + str(ycount + 2 * ccount) + "H",
                    *([v * 64 for v in y] + [word for v in chroma
                      for word in (v * 64, (1023 - v) * 64)])),
            }
            for index, payload in payloads.items():
                paths[index].write_bytes(payload)
            self.validated(self.invoke(paths, (str(width), str(height))),
                           [ycount, ccount, ccount], 4)

    def test_host_build_never_attempts_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            result = self.invoke(paths, node="/dev/dri/renderD128")
            self.rejected(result)


if __name__ == "__main__":
    unittest.main()
