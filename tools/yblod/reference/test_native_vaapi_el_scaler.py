"""Optional replay of real-SDK declarations; no driver or GPU invocation."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import unittest


class BorrowedScalerContracts(unittest.TestCase):
    def test_saved_synthetic_hardware_gate(self):
        root = Path(__file__).resolve().parent
        report = json.loads((root / "VAAPI_EL_SCALER_RESULTS.json").read_text())
        self.assertEqual(report["schema"], "yblod.borrowed-vaapi-el-scaler-checkpoint.v1")
        result = report["result"]
        self.assertEqual(result["input_size"], [32, 32])
        self.assertEqual(result["output_size"], [64, 64])
        self.assertEqual((result["frames"], result["words_per_frame"]), (2, 6144))
        self.assertEqual(result["fractional_words"], [0, 0])
        self.assertEqual(result["constant_mismatches"], 0)
        self.assertEqual(result["raw_filter_caps"], 0)
        self.assertFalse(result["helper_cpu_pixel_transfers"])
        self.assertFalse(result["egl_import_tested"])
        self.assertFalse(result["annex_b_equivalence_proven"])
        self.assertTrue(result["cleanup_complete"])
        for flag in ("kodi_active_before_after", "kodi_identity_unchanged", "artifacts_unchanged"):
            self.assertTrue(report[flag])
        resources = report["resources_after"]
        self.assertEqual(resources["memory.max"], "536870912")
        self.assertEqual(resources["memory.swap.max"], "0")
        self.assertEqual(resources["memory.swap.current"], "0")
        self.assertLess(int(resources["memory.peak"]), 536870912)
        self.assertTrue(all(value == "0" for name, value in
                            (line.split() for line in resources["memory.events"].splitlines())))
        for name, expected in report["source_sha256"].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)

    def run_probe(self, variable):
        executable = os.environ.get(variable)
        if not executable:
            self.skipTest(f"set {variable} to the strict SDK probe")
        result = subprocess.run([executable], check=True, capture_output=True,
                                text=True, timeout=5)
        return json.loads(result.stdout)

    def test_configuration_guards(self):
        result = self.run_probe("YB_VAAPI_EL_SCALER_CONTRACT_PROBE")
        self.assertEqual(result, {"checks": 21, "passed": True,
                                  "driver_called": False})

    def test_lifecycle_faults(self):
        result = self.run_probe("YB_VAAPI_EL_SCALER_FAULT_PROBE")
        self.assertEqual(result, {"fault_scenarios": 6, "passed": True,
                                  "hardware_test": False})


if __name__ == "__main__":
    unittest.main()
