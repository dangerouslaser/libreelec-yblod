"""Seeded bounded 2-D arithmetic checks independent of sampling_contract oracle."""
import ctypes as C
from fractions import Fraction as F
import random
import unittest

import test_native_sampling_probe as support
from sampling_contract import SamplingContract


class IndependentSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.NativeSamplingTests.setUpClass()
        cls.addClassCleanup(support.NativeSamplingTests.doClassCleanups)

    def test_seeded_bilinear_fraction_geometry_padding_and_wide_denominators(self):
        rng = random.Random(0x416B11)
        helper = support.NativeSamplingTests(methodName="runTest")
        for case in range(120):
            width, height = rng.randrange(1, 8), rng.randrange(1, 6)
            rows = [[rng.randrange(65536) for _ in range(width)] for _ in range(height)]
            bits = (16, 1, 3, 7)[case % 4]
            den = 1 << bits
            # Odd numerators force the highest declared fractional precision.
            coordinates = [F(rng.randrange(-2*den, 2*den) | 1, den) for _ in range(4)]
            contract = SamplingContract(width, height, *coordinates, "bilinear", (1 << 32)-1)
            queries = [(0, 0), (8191, 8191)] + [(rng.randrange(8), rng.randrange(8)) for _ in range(10)]
            owner, plane, native, query, out = helper.fixture(rows, contract, queries, padding=5)
            original = bytes(owner)
            self.assertEqual(helper.call(C.byref(plane), C.byref(native), query, len(query), out, len(out)), 0)
            self.assertEqual(bytes(owner), original)
            for (x, y), observed in zip(queries, out):
                sx = coordinates[0]+coordinates[2]*x
                sy = coordinates[1]+coordinates[3]*y
                ix, iy = sx.numerator//sx.denominator, sy.numerator//sy.denominator
                fx, fy = sx-ix, sy-iy
                expected = F(0)
                for dx, wx in ((0, 1-fx), (1, fx)):
                    for dy, wy in ((0, 1-fy), (1, fy)):
                        expected += wx*wy*rows[min(max(iy+dy, 0), height-1)][min(max(ix+dx, 0), width-1)]
                self.assertEqual(F(observed.raw_numerator, observed.raw_denominator), expected)
                self.assertEqual(F(observed.raw_numerator, observed.native_denominator), expected/64)
                self.assertEqual(F(observed.raw_numerator, observed.normalized_denominator), expected/((1 << 32)-1))
                self.assertEqual(F(observed.source_x_numerator, observed.coordinate_denominator), sx)
                self.assertEqual(F(observed.source_y_numerator, observed.coordinate_denominator), sy)

    def test_every_unsupported_route_keeps_whole_batch_untouched(self):
        helper = support.NativeSamplingTests(methodName="runTest")
        contract = SamplingContract(2, 2, F(-1, 2), F(1, 2), 1, -1, "bilinear", 65535)
        for name, values in (("native_depth", (0, 8, 12)), ("fractional_bits", (0, 4, 5, 7)),
                             ("method", (0, 3)), ("edge", (0, 2))):
            for value in values:
                with self.subTest(field=name, value=value):
                    _, plane, native, query, out = helper.fixture([[0, 65535], [32767, 32769]], contract, [(0, 0), (1, 1)])
                    setattr(native, name, value)
                    before = bytes(out)
                    self.assertEqual(helper.call(C.byref(plane), C.byref(native), query, 2, out, 2), 2)
                    self.assertEqual(bytes(out), before)


if __name__ == "__main__":
    unittest.main()
