"""Audit published synthetic measurement; no claim of fresh GPU execution."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "results/native-gpu-colour-synthetic-20261005k.json"


class PublishedColourMeasurement(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT.read_text())
        self.result = self.report["measurement"]

    def test_source_pins_and_scope(self):
        repo = ROOT.parents[2]
        for name, sha in self.report["sources"].items():
            self.assertEqual(hashlib.sha256((repo / name).read_bytes()).hexdigest(), sha)
        self.assertTrue(self.report["scope"]["public_synthetic_only"])
        for name in ("film_inputs", "decoder_tested", "playback_tested", "sk4_fit", "adoption_tolerance_selected"):
            self.assertFalse(self.report["scope"][name])
        self.assertFalse(self.result["tolerance_selected"])
        self.assertIsNone(self.result["adoption_pass"])

    def test_all_statuses_and_code_differences_are_included(self):
        records = self.result["records"]
        self.assertEqual(len(records), 72)
        self.assertEqual({(r["configuration"], r["sample"]) for r in records}, {(c, s) for c in range(6) for s in range(12)})
        self.assertEqual(sum(r["cpu_status"] != r["gpu_status"] for r in records), self.result["status_mismatches"])
        good = [r for r in records if r["cpu_status"] == 0 and r["gpu_status"] == 0]
        self.assertEqual(len(good), 34)
        differences = []
        for r in good:
            diff = [g - c for g, c in zip(r["gpu_codes"], r["cpu_codes"])]
            self.assertEqual(diff, r["code_signed_diff"])
            differences.extend(abs(x) for x in diff if x)
        self.assertEqual(len(differences), self.result["different_code_values"])
        self.assertEqual(max(differences, default=0), self.result["maximum_code_difference"])
        self.assertEqual(len(differences), 2)
        self.assertEqual([(r["configuration"], r["sample"]) for r in good if any(r["code_signed_diff"])], [(0, 4), (1, 4)])

    def test_stage_absolute_maxima_recompute_from_all_records(self):
        good = [r for r in self.result["records"] if r["cpu_status"] == 0 and r["gpu_status"] == 0]
        maxima = [max(value for r in good for value in r["stage_absolute_error"][stage]) for stage in range(4)]
        self.assertEqual(maxima, self.result["stage_max_abs"])
        self.assertTrue(all(value >= 0 for value in self.result["stage_max_relative"]))

    def test_resource_scope_and_privacy(self):
        r = self.report["resource_checks"]
        self.assertEqual(r["memory_max_bytes"], 512 * 1024**2)
        self.assertLess(r["memory_peak_bytes"], r["memory_max_bytes"])
        self.assertEqual(r["swap_current_bytes"], 0)
        self.assertEqual(r["swap_max_bytes"], 0)
        self.assertEqual(r["memory_limit_events"], 0)
        self.assertTrue(r["kodi_process_identity_unchanged"])
        self.assertTrue(r["files_and_runtime_unchanged"])
        self.assertEqual(r["runtime_pins"], 9)
        text = REPORT.read_text()
        for private in ("/storage/", "/home/", "/Users/", "start_ticks", '"pid"'):
            self.assertNotIn(private, text)
