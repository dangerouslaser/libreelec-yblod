"""Independent tiny preparation oracle; actual GPU measurement is separate."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent
BINARY = os.environ.get("YBLOD_GPU_PREPARATION_RUNNER_BINARY")


def oracle(operation, location, pattern):
    width = 4 if operation else 8
    channels = 2 if operation else 1
    def at(x, y, channel=0):
        x = max(0, min(width - 1, x))
        y = max(0, min(width - 1, y))
        if pattern == 0:
            return (64 + 37 * x + 83 * y + 127 * channel) % 1024
        if pattern == 1:
            return 1023 if x == width // 2 and y == width // 2 else 0
        return 1023 if (x + y + channel) % 2 else 0
    words, below, above = [], 0, 0
    for y in range(4):
        for x in range(4):
            for channel in range(channels):
                if not operation:
                    rows = [(at(2*x-1, 2*y+dy) + 2*at(2*x, 2*y+dy) + at(2*x+1, 2*y+dy) + 2) // 4 for dy in (0, 1)]
                    value = (sum(rows) + 1) // 2
                elif not location:
                    value = at(x, y, channel)
                elif operation == 1:
                    value = (3*at(x, y, channel) + at(x, y+1, channel) + 2) // 4
                else:
                    value = (-9*at(x, y-1, channel) + 111*at(x, y, channel) + 29*at(x, y+1, channel) - 3*at(x, y+2, channel) + 64) // 128
                if operation:
                    below += value < 0
                    above += value > 1023
                    value = max(0, min(1023, value)) << 6
                words.append(value)
    return words, [0, below, above]


class PreparationOracleContract(unittest.TestCase):
    def test_explicit_word_units_and_signed_floor(self):
        guide, status = oracle(0, 0, 0)
        phase, _ = oracle(1, 0, 0)
        # Edge horizontal rows round independently:73 and156, then115.
        self.assertEqual(guide[0], 115)
        self.assertEqual(phase[:2], [4096, 12224])
        self.assertEqual(status, [0, 0, 0])
        self.assertGreater(oracle(2, 1, 1)[1][1], 0)
        self.assertTrue(all(word & 63 == 0 for word in phase))


@unittest.skipUnless(BINARY, "set SDK binary for CPU-only oracle/CLI checks")
class CompiledPreparationOracle(unittest.TestCase):
    def test_actual_c_cpu_oracle_matches_independent_python(self):
        run = subprocess.run([BINARY, "--cpu-oracle"], check=True, capture_output=True, text=True, timeout=5)
        self.assertEqual(run.stderr, "")
        result = json.loads(run.stdout)
        self.assertFalse(result["gpu_executed"])
        self.assertEqual(len(result["cases"]), 11)
        for case in result["cases"]:
            words, status = oracle(case["operation"], case["chroma_location"], case["pattern"])
            self.assertEqual(case["expected_words"], words)
            self.assertEqual(case["expected_status"], status)

    def test_cli_guards_before_device_access(self):
        for args, expected in [((), "usage:"), (("x", "missing"), "explicit render node"), (("/dev/dri/renderD128", "/nonexistent-prep-shader"), "bounded regular shader")]:
            with self.subTest(args=args):
                run = subprocess.run([BINARY, *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(run.stdout, "")
                self.assertIn(expected, run.stderr)
