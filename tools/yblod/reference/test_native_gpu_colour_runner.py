"""Compiled CLI guards only; actual GPU accuracy must be measured separately."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
BINARY = os.environ.get("YBLOD_GPU_COLOUR_RUNNER_BINARY")


class RunnerContract(unittest.TestCase):
    def test_reports_all_errors_without_selecting_tolerance(self):
        source = (ROOT / "native_gpu_colour_runner.c").read_text()
        for field in ("stage_absolute_error", "stage_max_abs", "stage_max_relative", "status_mismatches", "code_signed_diff", "different_code_values", "input_float_conversion_max_abs", "uniform_float_conversion_max_abs"):
            self.assertIn(field, source)
        self.assertIn("tolerance_selected\\\":false", source)
        self.assertIn("adoption_pass\\\":null", source)
        self.assertIn("cpu_status[c][s]=yb_colour_sample", source)
        self.assertIn("GL_TRUE,converted", source)
        self.assertIn("sizeof(struct gpu_colour)==80", source)


@unittest.skipUnless(BINARY, "set YBLOD_GPU_COLOUR_RUNNER_BINARY for compiled CLI guards")
class RunnerCliGuards(unittest.TestCase):
    def test_rejects_before_gpu_device_open(self):
        for args, expected in [((), "usage:"), (("x", "missing"), "explicit render node"), (("/dev/dri/renderD128", "/nonexistent-colour-shader"), "bounded regular shader")]:
            with self.subTest(args=args):
                run = subprocess.run([BINARY, *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(run.stdout, "")
                self.assertIn(expected, run.stderr)

    def test_shader_guards_reject_nonregular_oversized_and_embedded_nul(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [root]
            for name, data in (("large", bytes(65537)), ("nul", b"a\0b"), ("empty", b"")):
                path = root / name
                path.write_bytes(data)
                cases.append(path)
            for path in cases:
                with self.subTest(path=path.name):
                    run = subprocess.run([BINARY, "/dev/dri/renderD128", str(path)], capture_output=True, text=True, timeout=5)
                    self.assertEqual(run.returncode, 1)
                    self.assertIn("bounded regular shader", run.stderr)
                    self.assertEqual(run.stdout, "")
