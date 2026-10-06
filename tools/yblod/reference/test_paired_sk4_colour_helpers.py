"""Focused CPU-only helper gates; no film fixtures, GPU or device access."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gpu_dump_colour_adapter as adapter
import run_paired_sk4_colour as driver
import sanitize_paired_sk4 as sanitizer


class HelperGates(unittest.TestCase):
    def test_regular_json_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "record.json"
            path.write_text('{"status":"complete"}')
            self.assertEqual(adapter.read_json(path), {"status": "complete"})
            alias = Path(folder) / "alias.json"
            alias.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "regular JSON"):
                adapter.read_json(alias)

    def test_json_bound_before_parse(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "oversize.json"
            with path.open("wb") as stream:
                stream.truncate((8 << 20) + 1)
            with self.assertRaisesRegex(ValueError, "regular JSON"):
                adapter.read_json(path)

    def test_only_qualified_geometry_before_fixture_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / "baseline"
            baseline.mkdir()
            (baseline / "report.json").write_text(json.dumps(dict(
                schema="yblod.composer-result.v1", status="complete",
                input_manifest=dict(width=1920, height=1080, metadata=dict(output_bit_depth=12)))))
            # Isolate the adapter's own geometry gate, not fake evidence that
            # the real reference/provenance validators accept this manifest.
            modules = {"reference": SimpleNamespace(validate=lambda _: None),
                       "colour_metadata": SimpleNamespace(load=lambda *_: None)}
            with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)):
                with self.assertRaisesRegex(ValueError, "only 4K/12bit"):
                    adapter.adapt(root, baseline, root, root, root, root, root / "output")
            self.assertFalse((root / "output").exists())

    def test_exact_resource_limits(self):
        snapshot = {"memory.max": "536870912", "memory.swap.max": "0",
                    "memory.swap.current": "0", "memory.events": "high 0\nmax 0\noom 0\noom_kill 0",
                    "cpu.max": "100000 100000"}
        driver.guard(snapshot)
        for key, value in (("memory.max", "max"), ("memory.swap.max", "1"),
                           ("memory.swap.current", "1"), ("cpu.max", "max 100000"),
                           ("cpu.max", "200000 100000"), ("memory.events", "high 0\nmax 1\noom 0\noom_kill 0")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                driver.guard({**snapshot, key: value})

    def test_scalar_summary_is_not_histogram_or_hash_export(self):
        result = sanitizer.scalars(dict(samples=100, changed_samples=2,
            maximum_absolute_codes=1, mean_absolute_codes=.02, rmse_codes=.1,
            signed_sum=0, signed_error_histogram=[{"error": 1, "count": 2}],
            private_sha256="secret", file="private/movie.raw"))
        self.assertEqual(result["identical_percent"], 98)
        self.assertEqual(result["mean_signed_codes"], 0)
        self.assertNotIn("private_sha256", result)
        self.assertNotIn("file", result)
        self.assertNotIn("signed_error_histogram", result)

    def test_summary_completion_and_capture_count(self):
        with self.assertRaisesRegex(ValueError, "completed"):
            sanitizer.sanitize({"status": "failed"}, 1943)
        with self.assertRaisesRegex(ValueError, "six saved"):
            sanitizer.sanitize(dict(schema="yblod.paired-sk4-native-colour-checkpoint.v1",
                status="complete", comparisons=[]), 1943)


if __name__ == "__main__":
    unittest.main()
