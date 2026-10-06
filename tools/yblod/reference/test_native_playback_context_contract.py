"""Real-production ABI invalid-argument replay, not a hardware test."""
import json
import os
import subprocess
import unittest


class PlaybackContextContract(unittest.TestCase):
    def test_real_c_guards(self):
        executable = os.environ.get("YB_NATIVE_PLAYBACK_CONTEXT_CONTRACT_PROBE")
        if not executable:
            self.skipTest("set YB_NATIVE_PLAYBACK_CONTEXT_CONTRACT_PROBE to full-library SDK probe")
        loader = os.environ.get("YB_NATIVE_PLAYBACK_CONTEXT_LOADER")
        library_path = os.environ.get("YB_NATIVE_PLAYBACK_CONTEXT_LIBRARY_PATH")
        self.assertEqual(bool(loader), bool(library_path), "loader and matching library path required together")
        command = [loader, "--library-path", library_path, executable] if loader else [executable]
        run = subprocess.run(command, check=True, capture_output=True,
                             text=True, timeout=5)
        self.assertEqual(json.loads(run.stdout), {
            "checks": 19, "passed": True, "gpu_attempted": False})


if __name__ == "__main__":
    unittest.main()
