"""Independent saved wrapper output and pending-lifetime evidence checks."""
import json
from pathlib import Path
import unittest
from test_native_gpu_preparation_runner import oracle
import test_native_gpu_preparation_results as evidence_checks

class SavedApiEvidence(unittest.TestCase):
    def test_all_observed_words_statuses_and_lifetimes(self):
        path = Path(__file__).resolve().parent / "results/native-gpu-preparation-api-synthetic-20261005p.json"
        result = json.loads(path.read_text())
        evidence_checks.SavedGpuPreparationEvidence().check_resources(result)
        self.assertEqual(result["schema"], "yblod.gpu-preparation-api-synthetic-probe.v1")
        self.assertEqual(result["busy_submit_checks"], 11)
        self.assertEqual(result["pending_destroy_checks"], 11)
        self.assertTrue(result["evidence"]["frame_and_contract_tokens_checked"])
        self.assertEqual(len(result["cases"]), 11)
        self.assertEqual(result["compared_words"], 304)
        self.assertEqual(result["word_mismatches"], 0)
        self.assertEqual(result["status_mismatches"], 0)
        for case in result["cases"]:
            words, status = oracle(case["operation"], case["chroma_location"], case["pattern"])
            self.assertEqual(case["actual_words"], words)
            self.assertEqual(case["expected_words"], words)
            self.assertEqual(case["actual_status"], status)
            self.assertEqual(case["expected_status"], status)
        self.assertEqual(sum(len(c["actual_words"]) for c in result["cases"]), 304)
