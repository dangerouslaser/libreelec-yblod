import unittest

from hardware_phase_check import BASES, affine_planes, analyse
from scaling_probe import pack_p010


class AffineCheckTests(unittest.TestCase):
    def test_sources_have_exact_native_step_and_valid_codes(self):
        for axis in ("x", "y"):
            planes = affine_planes(axis)
            pack_p010(planes)
            for c, rows in planes.items():
                self.assertEqual(rows[0][0], BASES[c])
                self.assertEqual(rows[0][1] - rows[0][0] if axis == "x" else rows[1][0] - rows[0][0], 8)

    def test_independent_zero_and_quarter_native_phase_predictions(self):
        for axis in ("x", "y"):
            for bias in (0, 2, -2):
                planes = {c: [[BASES[c] + 4 * (x if axis == "x" else y)
                               - (2 if axis == "y" else 0) + bias
                               for x in range(128 if c == "Y" else 64)]
                              for y in range(128 if c == "Y" else 64)] for c in BASES}
                report = analyse(axis, pack_p010(planes))
                for c in BASES:
                    self.assertEqual(report["channels"][c]["interior_error_values"], [bias])
                    self.assertEqual(report["channels"][c]["interior_step_values"], [4])

    def test_invalid_axis_and_low_bit_contract_rejected(self):
        with self.assertRaises(ValueError): affine_planes("z")
        with self.assertRaises(ValueError): analyse("z", b"")
        with self.assertRaises(ValueError): analyse("x", b"\1\0" + bytes(128 * 128 * 3 - 2))

    def test_reversed_sources_are_exact_mirrors_and_phase_sign_reverses(self):
        for axis in ("x", "y"):
            ascending, descending = affine_planes(axis), affine_planes(axis + "-desc")
            for c in BASES:
                expected = [row[::-1] for row in ascending[c]] if axis == "x" else ascending[c][::-1]
                self.assertEqual(descending[c], expected)
            planes = {c: [[BASES[c] + 8 * ((64 if c == "Y" else 32) - 1)
                           - 4 * (x if axis == "x" else y) + (2 if axis == "y" else 0) - 2
                           for x in range(128 if c == "Y" else 64)]
                          for y in range(128 if c == "Y" else 64)] for c in BASES}
            report = analyse(axis + "-desc", pack_p010(planes))
            for c in BASES:
                self.assertEqual(report["channels"][c]["interior_error_values"], [-2])
                self.assertEqual(report["channels"][c]["interior_step_values"], [-4])


if __name__ == "__main__":
    unittest.main()
