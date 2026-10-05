import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from inspect_composition import inspect, stats
from make_demo import make_demo
from reference import run


class InspectionTest(unittest.TestCase):
    def test_difference_sign_and_thresholds(self):
        result = stats(np.array([0, 100, 4095], dtype=np.uint16),
                       np.array([0, 101, 0], dtype=np.uint16))
        self.assertEqual(result["maximum_absolute_codes"], 4095)
        self.assertAlmostEqual(result["identical_percent"], 100 / 3)

    def test_saved_arithmetic_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_demo(root / "input")
            run(root / "input/frame.json", root / "output")
            result = inspect(root / "output")
            self.assertTrue(result["channels"]["Y"]["signed_addition_verified"])
            self.assertTrue(result["channels"]["Y"]["final_rounding_and_bounds_verified"])
            self.assertEqual(result["channels"]["Y"]["rounded_below_zero"], 0)
            (root / "output/sum_Y.i32le").write_bytes(b"\0" * 32)
            with self.assertRaisesRegex(ValueError, "integrity"):
                inspect(root / "output")


if __name__ == "__main__":
    unittest.main()
