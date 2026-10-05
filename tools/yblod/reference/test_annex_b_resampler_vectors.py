"""Literal, hand-derived Annex B EL answers, independent of filter adapters.

No physical chroma-registration or licensed-Dolby conformance assertion.
The integer-tap implementation below is test-only, not a selected backend.
"""
from fractions import Fraction
import unittest

from scaling_oracle import expand


SOURCE = ((0, 1), (2, 8))
Y_VERTICAL = ((0, 1), (0, 2), (2, 7), (2, 8))
C_VERTICAL = ((0, 1), (1, 3), (2, 6), (2, 8))
Y_OUTPUT = ((0, 1, 1, 1), (0, 1, 2, 2),
            (2, 5, 7, 7), (2, 5, 8, 9))
C_OUTPUT = ((0, 1, 1, 1), (1, 2, 3, 3),
            (2, 4, 6, 6), (2, 5, 8, 9))


def tap(samples, origin, offsets, coefficients):
    return sum(coefficient * samples[min(len(samples)-1, max(0, origin+offset))]
               for offset, coefficient in zip(offsets, coefficients))


def bound_round(numerator, denominator):
    # // is mathematical floor, including negative numerators. This is NOT
    # truncating signed division and does not depend on signed right shifts.
    return min(65535, max(0, (numerator+denominator//2)//denominator))


def integer_taps(rows, component):
    columns = tuple(zip(*rows))
    vertical = []
    for output_y in range(len(rows)*2):
        n, odd = divmod(output_y, 2)
        if component == "Y":
            offsets = (-1, 0, 1, 2) if odd else (-2, -1, 0, 1)
            coefficients = (-9, 111, 29, -3) if odd else (-3, 29, 111, -9)
            denominator = 128
        else:
            offsets = (0, 1) if odd else (-1, 0)
            coefficients = (192, 64) if odd else (64, 192)
            denominator = 256
        vertical.append(tuple(bound_round(tap(column, n, offsets, coefficients), denominator)
                              for column in columns))
    output = []
    for row in vertical:
        output.append(tuple(row[x//2] if not x % 2 else bound_round(
            tap(row, x//2, tuple(range(-3, 5)), (22, 94, -524, 2456, 2456, -524, 94, 22)),
            4096) for x in range(len(row)*2)))
    return tuple(output), tuple(vertical)


class AnnexBResamplerVectors(unittest.TestCase):
    def test_literal_integer_taps(self):
        for component, vertical, output in (("Y", Y_VERTICAL, Y_OUTPUT),
                                            ("Cb", C_VERTICAL, C_OUTPUT),
                                            ("Cr", C_VERTICAL, C_OUTPUT)):
            with self.subTest(component=component):
                self.assertEqual(integer_taps(SOURCE, component), (output, vertical))

    def test_independent_fraction_oracle_against_literal_answers(self):
        for component, vertical, output in (("Y", Y_VERTICAL, Y_OUTPUT),
                                            ("Cb", C_VERTICAL, C_OUTPUT),
                                            ("Cr", C_VERTICAL, C_OUTPUT)):
            with self.subTest(component=component):
                actual, intermediate, _ = expand(SOURCE, component)
                self.assertEqual(tuple(map(tuple, intermediate)), vertical)
                self.assertEqual(tuple(map(tuple, actual)), output)

    def test_per_pass_rounding_discriminator(self):
        # Before vertical rounding, the first two Y samples are -18/128 and
        # 65/128. Their horizontal midpoint is 47/256, rounding to zero.
        # Required vertical rounding first yields [0,1], then midpoint 1/2 -> 1.
        deferred = (Fraction(-18, 128)+Fraction(65, 128))/2
        self.assertEqual(deferred, Fraction(47, 256))
        self.assertEqual(bound_round(deferred.numerator, deferred.denominator), 0)
        self.assertEqual(Y_OUTPUT[0][1], 1)

    def test_edge_ringing_not_bilinear_and_unsigned16_clip(self):
        self.assertEqual(Fraction(-408*2+4504*8, 4096), Fraction(2201, 256))
        self.assertEqual(bound_round(35216, 4096), 9)
        self.assertEqual(Y_OUTPUT[3][3], 9)  # repeated-edge bilinear would give 8
        output, vertical = integer_taps(((0, 65535), (65535, 0)), "Y")
        self.assertEqual(vertical, ((0, 65535), (13312, 52223),
                                    (52223, 13312), (65535, 0)))
        self.assertTrue(all(0 <= sample <= 65535 for row in output for sample in row))
        # Native10 inputs may produce a reference value above native10 maximum.
        _, native_vertical = integer_taps(((0, 1023), (1023, 0)), "Y")
        self.assertEqual(native_vertical[0], (0, 1095))


if __name__ == "__main__":
    unittest.main()
