"""Independent literal-filter oracle, not a universal Dolby scaling claim."""
import json
import os
import subprocess
import unittest

BINARY = os.environ.get("YBLOD_GPU_EL_SCALING_RUNNER_BINARY")


def oracle(component, pattern):
    channels = 2 if component else 1
    def bound(index):
        return max(0, min(3, index))
    def source(x, y, channel):
        x, y = bound(x), bound(y)
        if pattern == 0:
            return 512
        if pattern == 1:
            return 64 + 37*x + 83*y + 127*channel
        if pattern == 3:
            return 1023 if x >= 2 else 0
        return (128 if pattern == 2 else 1023) if x == 2 and y == 2 else 0
    def rounded(value, bits):
        return max(0, min(65535, (value + (1 << (bits-1))) // (1 << bits)))
    vertical = []
    for y in range(8):
        for x in range(4):
            for channel in range(channels):
                if component:
                    offsets = (0, 1) if y % 2 else (-1, 0)
                    weights = (192, 64) if y % 2 else (64, 192)
                    bits = 8
                else:
                    offsets = (-1, 0, 1, 2) if y % 2 else (-2, -1, 0, 1)
                    weights = (-9, 111, 29, -3) if y % 2 else (-3, 29, 111, -9)
                    bits = 7
                vertical.append(rounded(sum(source(x, y//2+offset, channel)*weight for offset, weight in zip(offsets, weights)), bits))
    output, status = [], 0
    for y in range(8):
        for x in range(8):
            values = []
            for channel in range(channels):
                if x % 2:
                    weights = (22, 94, -524, 2456, 2456, -524, 94, 22)
                    values.append(rounded(sum(vertical[(y*4+bound(x//2+offset))*channels+channel]*weight for offset, weight in zip(range(-3, 5), weights)), 12))
                else:
                    values.append(vertical[(y*4+x//2)*channels+channel])
            rejected = any(value > 1023 for value in values)
            status |= 4 if rejected else 0
            output.extend([65535]*channels if rejected else [value << 6 for value in values])
    return vertical, output, status


class ExplicitAnchors(unittest.TestCase):
    def test_constant_word_units(self):
        for component in (0, 1):
            vertical, output, status = oracle(component, 0)
            self.assertEqual(set(vertical), {512})
            self.assertEqual(set(output), {32768})
            self.assertEqual(status, 0)

    def test_overshoot_rejected_not_hidden(self):
        self.assertEqual(oracle(0, 3)[2], 4)
        self.assertIn(65535, oracle(0, 3)[1])
        self.assertEqual(oracle(0, 2)[2], 0)


@unittest.skipUnless(BINARY, "set SDK binary for actual CPU-only oracle")
class ActualCpuOracle(unittest.TestCase):
    def test_ten_cases(self):
        result = json.loads(subprocess.check_output([BINARY, "--cpu-oracle"], text=True, timeout=5))
        self.assertFalse(result["gpu_executed"])
        self.assertEqual(len(result["cases"]), 10)
        for case in result["cases"]:
            vertical, words, status = oracle(case["component"], case["pattern"])
            self.assertEqual(case["expected_vertical"], vertical)
            self.assertEqual(case["expected_words"], words)
            self.assertEqual(case["expected_status"], status)
