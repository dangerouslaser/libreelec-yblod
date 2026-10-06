"""Real patched-FFmpeg fixture replay, optional SDK binary; no GPU/media."""
import json
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get("YB_PLAYBACK_METADATA_PROBE"), "matching SDK fixture binary required")
class PlaybackMetadataTests(unittest.TestCase):
    def run_case(self, case):
        run = subprocess.run([os.environ["YB_PLAYBACK_METADATA_PROBE"], str(case)],
                             capture_output=True, text=True, check=True, timeout=5)
        return json.loads(run.stdout)

    def test_owned_success(self):
        for case, native in ((0, 1), (17, 0)):
            result = self.run_case(case)
            self.assertEqual(result["status"], 0)
            self.assertTrue(result["owned_configs_after_input_release"])
            self.assertEqual(result["has_native_colour"], native)

    def test_actual_adapters_and_route_failures_atomic(self):
        expected = {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 5, 7: 5,
                    8: 5, 9: 3, 10: 4, 11: 4, 12: 3, 13: 6,
                    14: 5, 15: 3, 16: 2, 18: 1, 19: 5, 20: 1, 21: 1}
        for case, status in expected.items():
            with self.subTest(case=case):
                result = self.run_case(case)
                self.assertEqual(result["status"], status)
                self.assertTrue(result["failure_atomic"])


if __name__ == "__main__":
    unittest.main()
