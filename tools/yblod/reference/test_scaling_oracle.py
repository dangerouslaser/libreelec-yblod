"""Synthetic-only EL scaler alignment/rounding checks; no hardware fitting."""
from fractions import Fraction as F
import unittest

from scaling_oracle import expand, horizontal_point, round_bound, vertical_point

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    import prepare_frame


class ScalingScalarTests(unittest.TestCase):
    def test_coordinates_on_interior_affine_ramps(self):
        samples = [1000+128*i for i in range(14)]
        for component in ("Y", "Cb", "Cr"):
            for output in range(4, 22):
                self.assertEqual(vertical_point(samples, output, component),
                                 1000+128*(F(output, 2)-F(1, 4)))
        for output in range(6, 21):
            self.assertEqual(horizontal_point(samples, output), 1000+128*F(output, 2))
        # Even/odd vertical phases are n-1/4 and n+1/4. Horizontal phases
        # are n and n+1/2. Physical BL alignment additionally needs the
        # input registration and native phase adapter; this test does not
        # establish them from filter moments alone.

    def test_luma_impulse_values_derived_from_polynomial(self):
        samples = [0, 0, 0, 128, 0, 0, 0]
        self.assertEqual([vertical_point(samples, y, "Y") for y in range(14)],
                         [0, 0, 0, -3, -9, 29, 111, 111, 29, -9, -3, 0, 0, 0])

    def test_chroma_impulse_values(self):
        samples = [0, 0, 256, 0, 0]
        self.assertEqual([vertical_point(samples, y, "Cb") for y in range(10)],
                         [0, 0, 0, 64, 192, 192, 64, 0, 0, 0])

    def test_midpoint_rounding_is_not_bankers_rounding(self):
        for value, expected in ((F(1, 2), (1, 1)), (F(-1, 2), (0, 0)),
                                (F(-3, 2), (0, -1)), (F(131071, 2), (65535, 65536))):
            self.assertEqual(round_bound(value), expected)
        self.assertEqual(vertical_point([0, 2], 1, "Cb"), F(1, 2))
        # The central horizontal coefficient on a single 256 impulse
        # produces an exact half, before the explicit bound.
        self.assertEqual(horizontal_point([0, 0, 0, 256, 0, 0, 0, 0], 7), F(307, 2))

    def test_constants_and_single_sample_replicated_edges(self):
        for component in ("Y", "Cb", "Cr"):
            for value in (0, 1, 512, 1023, 65535):
                result, vertical, _ = expand([[value]], component)
                self.assertEqual(result, [[value, value], [value, value]])
                self.assertEqual(vertical, [[value], [value]])

    def test_vertical_rounding_occurs_before_horizontal(self):
        rows = [[0, 0, 0, 2, 0, 0, 0, 0], [0]*8]
        output, vertical, _ = expand(rows, "Cb")
        self.assertEqual(vertical[1][3], 2)  # 3/4*2 = 1.5 -> 2
        self.assertEqual(output[1][7], 1)    # 307/512*2 -> 1
        # Unrounded fusion would be 307/512*1.5 -> 1 too here. A separate
        # sample demonstrates the observable difference from pass fusion.
        rows = [[0, 0, 0, 1, 0, 0, 0, 0], [0]*8]
        output, _, _ = expand(rows, "Cb")
        fused = round_bound(F(3, 4)*F(307, 512))[0]
        self.assertEqual(output[1][7], 1)
        self.assertEqual(fused, 0)

    def test_invalid_inputs_fail(self):
        for rows in ([], [[]], [[1], [1, 2]], [[-1]], [[65536]], [[True]], [[F(1)]]):
            with self.assertRaises(ValueError):
                expand(rows, "Y")


@unittest.skipIf(np is None, "NumPy required for production scaler comparison")
class ScalingImplementationTests(unittest.TestCase):
    def check(self, rows, component):
        expected, vertical, stats = expand(rows, component)
        source = np.asarray(rows, dtype=np.uint16)
        source.flags.writeable = False
        output, actual_vertical, measured = prepare_frame.upsample_el(source, component)
        np.testing.assert_array_equal(output, expected)
        np.testing.assert_array_equal(actual_vertical, vertical)
        np.testing.assert_array_equal(source, rows)
        for stage, fields in stats.items():
            for key, value in fields.items():
                self.assertEqual(measured[stage][key], value, (component, stage, key))

    def test_constants_tiny_and_asymmetric_shapes(self):
        for shape in ((1, 1), (1, 9), (7, 1), (3, 11)):
            for component in ("Y", "Cb", "Cr"):
                for value in (0, 512, 65535):
                    self.check([[value]*shape[1] for _ in range(shape[0])], component)

    def test_affine_and_asymmetric_quadratic_patterns(self):
        for rows in ([[1000+64*y+128*x for x in range(11)] for y in range(9)],
                     [[(173*y*y+619*x+71*x*y)%65536 for x in range(13)] for y in range(17)]):
            for component in ("Y", "Cb", "Cr"):
                self.check(rows, component)

    def test_first_middle_last_impulses_and_negative_lobes(self):
        for iy, ix in ((0, 0), (3, 5), (6, 10)):
            for background, impulse in ((0, 65535), (65535, 0), (512, 1023)):
                rows = [[impulse if (y, x) == (iy, ix) else background
                         for x in range(11)] for y in range(7)]
                for component in ("Y", "Cb", "Cr"):
                    self.check(rows, component)

    def test_alternating_rows_columns_and_halfway_values(self):
        for rows in ([[65535*(y%2) for x in range(9)] for y in range(11)],
                     [[65535*(x%2) for x in range(9)] for y in range(11)],
                     [[(2*y+256*x)%1024 for x in range(9)] for y in range(11)]):
            for component in ("Y", "Cb", "Cr"):
                self.check(rows, component)

    def test_chunk_boundaries_address_full_source_not_chunk_edge(self):
        rows = [[(997*y*y+73*x+199*x*y)%65536 for x in range(5)] for y in range(67)]
        original = prepare_frame.FIR_CHUNK_ROWS
        try:
            for chunk in (1, 7, 32, 128):
                prepare_frame.FIR_CHUNK_ROWS = chunk
                for component in ("Y", "Cb", "Cr"):
                    self.check(rows, component)
        finally:
            prepare_frame.FIR_CHUNK_ROWS = original


if __name__ == "__main__":
    unittest.main()
