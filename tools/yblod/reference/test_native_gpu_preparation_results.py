"""Saved public synthetic evidence independently recomputed, not exit-code checks."""
import json
from pathlib import Path
import unittest
from test_native_gpu_preparation_runner import oracle as preparation_oracle
from test_native_gpu_el_scaling_runner import oracle as scaling_oracle

ROOT = Path(__file__).resolve().parent


class SavedGpuPreparationEvidence(unittest.TestCase):
    def check_resources(self, result):
        evidence = result["evidence"]
        self.assertEqual(evidence["memory_limit_bytes"], 536870912)
        self.assertLess(evidence["memory_peak_bytes"], evidence["memory_limit_bytes"])
        self.assertEqual(evidence["job_swap_bytes"], 0)
        self.assertEqual(evidence["memory_pressure_events"], 0)
        self.assertTrue(evidence["kodi_identity_unchanged"])
        self.assertTrue(evidence["files_and_runtime_unchanged"])
        self.assertTrue(evidence["independent_python_oracle_pass"])
        self.assertEqual(evidence["runtime_pin_count"], 9)
        self.assertEqual(evidence["timeout_seconds"], 30)
        self.assertTrue(result["complete"])
        self.assertTrue(result["cleanup_complete"])
        self.assertFalse(result["playback_tested"])

    def test_saved_guide_phase(self):
        result = json.loads((ROOT / "results/native-gpu-preparation-synthetic-20261005n.json").read_text())
        self.check_resources(result)
        self.assertEqual(result["compared_words"], 304)
        self.assertEqual(len(result["cases"]), 11)
        self.assertEqual(result["word_mismatches"], 0)
        self.assertEqual(result["status_mismatches"], 0)
        self.assertEqual(result["evidence"]["observed_status_fields"], 33)
        for case in result["cases"]:
            words, status = preparation_oracle(case["operation"], case["chroma_location"], case["pattern"])
            self.assertEqual(case["actual_words"], words)
            self.assertEqual(case["expected_words"], words)
            self.assertEqual(case["actual_status"], status)
            self.assertEqual(case["expected_status"], status)
        self.assertEqual(sum(len(c["actual_words"]) for c in result["cases"]), 304)
        self.assertEqual([sum(c["actual_status"][i] for c in result["cases"]) for i in (1, 2)], [8, 4])

    def test_saved_literal_scaling(self):
        result = json.loads((ROOT / "results/native-gpu-el-scaling-synthetic-20261005o.json").read_text())
        self.check_resources(result)
        self.assertEqual(len(result["cases"]), 10)
        self.assertEqual(result["compared_words"], 1440)
        self.assertEqual(result["evidence"]["observed_status_fields"], 10)
        for name in ("final_word_mismatches", "vertical_word_mismatches", "status_mismatches"):
            self.assertEqual(result[name], 0)
        for case in result["cases"]:
            vertical, words, status = scaling_oracle(case["component"], case["pattern"])
            self.assertEqual(case["actual_vertical"], vertical)
            self.assertEqual(case["expected_vertical"], vertical)
            self.assertEqual(case["actual_words"], words)
            self.assertEqual(case["expected_words"], words)
            self.assertEqual(case["actual_status"], status)
            self.assertEqual(case["expected_status"], status)
        self.assertEqual(sum(len(c["actual_vertical"])+len(c["actual_words"]) for c in result["cases"]), 1440)
        self.assertEqual([(c["component"], c["pattern"]) for c in result["cases"] if c["actual_status"]], [(0, 3), (1, 3)])
