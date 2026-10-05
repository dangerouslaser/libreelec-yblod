"""Optional compiled-probe argument/input guards; these never open a GPU."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BINARY = os.environ.get("YBLOD_VAAPI_PROBE_BINARY")


@unittest.skipUnless(BINARY, "set YBLOD_VAAPI_PROBE_BINARY to test compiled CLI guards")
class CompiledProbeGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "input.p010"
        self.source.write_bytes(bytes(16 * 16 * 3))
        self.output = self.root / "new-output.p010"

    def reject(self, expected, *, iw="16", ih="16", ow="16", oh="16", mode="copy", extra=()):
        # A nonexistent device is deliberate. Every assertion must reject the
        # input BEFORE trying to open it, not pass due to missing GPU access.
        args = [BINARY, "/nonexistent-yblod-render-device", str(self.source), str(self.output),
                iw, ih, ow, oh, mode, *extra]
        run = subprocess.run(args, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(expected, run.stderr)
        self.assertNotIn("open render device", run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertFalse(self.output.exists())

    def test_usage_without_device_access(self):
        run = subprocess.run([BINARY], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("usage:", run.stderr)

    def test_dimensions_rejected_before_device_access(self):
        for value in ("0", "1", "3", "4098", "-2", "16.0", "", "16garbage"):
            with self.subTest(value=value): self.reject("dimensions must", iw=value)

    def test_copy_cannot_resize(self):
        self.reject("copy test requires identical dimensions", ow="32")

    def test_unknown_filter_is_not_silently_defaulted(self):
        self.reject("unknown filter request", mode="made-up-quality")

    def test_input_length_rejected_before_device_access(self):
        for size in (0, 16 * 16 * 3 - 2, 16 * 16 * 3 + 2):
            self.source.write_bytes(bytes(size))
            self.reject("exactly one tightly packed P010 frame")

    def test_unused_low_bits_are_not_silently_discarded(self):
        self.source.write_bytes(b"\1\0" + bytes(16 * 16 * 3 - 2))
        self.reject("nonzero low six bits")

    def test_chroma_options_fail_closed(self):
        for extra, expected in (
            (("--input-chroma",), "usage:"),
            (("--other", "left"), "unknown chroma option"),
            (("--input-chroma", "center"), "unknown chroma location"),
            (("--output-chroma", "left", "--output-chroma", "top-left"), "duplicate chroma option"),
        ):
            with self.subTest(extra=extra): self.reject(expected, mode="default", extra=extra)

    def test_copy_rejects_siting_declarations(self):
        self.reject("copy test does not accept chroma declarations", extra=("--input-chroma", "left"))

    def test_pipeline_options_fail_closed(self):
        for extra, expected in (
            (("--pipeline",), "usage:"),
            (("--pipeline", "render"), "unknown pipeline request"),
            (("--pipeline", "fast", "--pipeline", "default"), "duplicate pipeline option"),
        ):
            with self.subTest(extra=extra): self.reject(expected, mode="default", extra=extra)

    def test_copy_rejects_pipeline_declarations(self):
        for value in ("default", "fast"):
            with self.subTest(value=value):
                self.reject("copy test does not accept pipeline declarations", extra=("--pipeline", value))

    def test_format_options_fail_closed(self):
        for extra, expected in (
            (("--output-format",), "usage:"),
            (("--output-format", "y412"), "unknown output format request"),
            (("--output-format", "y416", "--output-format", "p010"), "duplicate output format option"),
        ):
            with self.subTest(extra=extra): self.reject(expected, mode="default", extra=extra)

    def test_range_options_fail_closed(self):
        for extra, expected in (
            (("--range",), "usage:"),
            (("--range", "auto"), "unknown range request"),
            (("--range", "full", "--range", "reduced"), "duplicate range option"),
        ):
            with self.subTest(extra=extra): self.reject(expected, mode="default", extra=extra)

    def test_copy_cannot_convert_or_declare_range(self):
        self.reject("copy test requires P010 output", extra=("--output-format", "y416"))
        for value in ("full", "reduced"):
            with self.subTest(value=value):
                self.reject("copy test does not accept range declarations", extra=("--range", value))

    def test_input_siting_cannot_be_unspecified(self):
        self.reject("unknown chroma location", mode="default", extra=("--input-chroma", "unspecified"))


if __name__ == "__main__":
    unittest.main()
