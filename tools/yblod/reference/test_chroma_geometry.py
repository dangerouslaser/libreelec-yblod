"""Device-independent phase/filter checks with exact rational expectations.

No captured pixels or production expansion routine generate expected values.
The Fraction oracle and literal impulse/ramp answers deliberately distinguish
left-sited from top-left/centered sampling. Candidate filters are experiments,
not documented Dolby requirements. Production checks need NumPy.
"""
from fractions import Fraction as F
import unittest

from chroma_geometry_oracle import expand, interpolate

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    from output_frame import expand_left
    from chroma_geometry import expand as candidate_expand


V_LINEAR = (0, 0, 0, 4, 12, 12, 4, 0, 0, 0)
H_LINEAR = (0, 0, 0, 8, 16, 8, 0, 0, 0, 0)
V_CUBIC = (0, F(-3, 8), F(-9, 8), F(29, 8), F(111, 8),
           F(111, 8), F(29, 8), F(-9, 8), F(-3, 8), 0)
H_CUBIC = (0, -1, 0, 9, 16, 9, 0, -1, 0, 0)


class ExactGeometryTests(unittest.TestCase):
    def test_quarter_chroma_row_not_half_chroma_row(self):
        plane = [[0, 0], [16, 16], [32, 32]]
        self.assertEqual([row[0] for row in expand(plane)], [0, 4, 12, 20, 28, 32])

    def test_explicit_linear_impulses(self):
        self.assertEqual([row[0] for row in expand([[v] for v in (0, 0, 16, 0, 0)])], list(V_LINEAR))
        self.assertEqual(expand([[0, 0, 16, 0, 0]])[0], list(H_LINEAR))

    def test_cubic_hermite_against_exact_keys_impulse_values(self):
        # For a=-1/2: kernel(1/4)=111/128, kernel(3/4)=29/128,
        # kernel(5/4)=-9/128, kernel(7/4)=-3/128. Impulse amplitude is16.
        self.assertEqual([row[0] for row in expand([[v] for v in (0, 0, 16, 0, 0)], "cubic")], list(V_CUBIC))
        self.assertEqual(expand([[0, 0, 16, 0, 0]], "cubic")[0], list(H_CUBIC))

    def test_constant_including_single_sample_and_shifted_edges(self):
        for kernel in ("linear", "cubic"):
            for plane in ([[37]], [[37]*4 for _ in range(3)]):
                for dx, dy in ((0, 0), (F(1, 2), 0), (0, F(-1, 2))):
                    result = expand(plane, kernel, dx=dx, dy=dy)
                    self.assertTrue(all(value == 37 for row in result for value in row))

    def test_explicit_rectangular_ramp(self):
        plane = [[100+8*x+16*y for x in range(4)] for y in range(3)]
        horizontal = [0, 4, 8, 12, 16, 20, 24, 24]
        vertical = [0, 4, 12, 20, 28, 32]
        self.assertEqual(expand(plane), [[100+x+y for x in horizontal] for y in vertical])

    def test_wrong_vertical_phase_controls_keep_horizontal_unchanged(self):
        vertical = [[0], [16], [32]]
        self.assertEqual([row[0] for row in expand(vertical, dy=F(1, 2))], [0, 8, 16, 24, 32, 32])
        self.assertEqual([row[0] for row in expand(vertical, dy=F(-1, 2))], [0, 0, 8, 16, 24, 32])
        horizontal = [[0, 16, 0]]*4
        for kernel in ("linear", "cubic"):
            self.assertEqual(expand(horizontal, kernel, dy=F(1, 2)), expand(horizontal, kernel))
            self.assertEqual(expand(horizontal, kernel, dy=F(-1, 2)), expand(horizontal, kernel))

    def test_wrong_horizontal_phase_controls_keep_vertical_unchanged(self):
        horizontal = [[0, 16, 32]]
        self.assertEqual(expand(horizontal, dx=F(1, 2))[0], [4, 12, 20, 28, 32, 32])
        self.assertEqual(expand(horizontal, dx=F(-1, 2))[0], [0, 4, 12, 20, 28, 32])
        vertical = [[value]*4 for value in (0, 16, 0)]
        for kernel in ("linear", "cubic"):
            self.assertEqual(expand(vertical, kernel, dx=F(1, 2)), expand(vertical, kernel))
            self.assertEqual(expand(vertical, kernel, dx=F(-1, 2)), expand(vertical, kernel))

    def test_no_cubic_intermediate_clamp_or_rounding(self):
        self.assertEqual(interpolate([0, 0, 16, 0, 0], F(3, 4), "cubic"), F(-9, 8))
        self.assertEqual(interpolate([0, 0, 16, 0, 0], F(7, 4), "cubic"), F(111, 8))

    def test_separable_two_dimensional_impulse(self):
        plane = [[0]*5 for _ in range(5)]
        plane[2][2] = 256
        for kernel, vertical, horizontal in (("linear", V_LINEAR, H_LINEAR), ("cubic", V_CUBIC, H_CUBIC)):
            self.assertEqual(expand(plane, kernel), [[y*x for x in horizontal] for y in vertical])

    def test_strip_coordinates_are_global_not_relative_to_strip(self):
        plane = [[100+8*x+16*y for x in range(4)] for y in range(5)]
        for kernel in ("linear", "cubic"):
            full = expand(plane, kernel)
            pieces = expand(plane, kernel, start=0, stop=1)
            pieces += expand(plane, kernel, start=1, stop=7)
            pieces += expand(plane, kernel, start=7, stop=10)
            self.assertEqual(pieces, full)


@unittest.skipIf(np is None, "NumPy required for implementation geometry checks")
class ProductionLinearGeometryTests(unittest.TestCase):
    def assert_expansion(self, plane, start=0, stop=None):
        expected = np.array(expand(plane, start=start, stop=stop), dtype=float)
        actual = expand_left(np.array(plane, dtype=np.uint16), start, stop)
        np.testing.assert_array_equal(actual, expected)

    def test_literal_vertical_and_horizontal_impulses(self):
        np.testing.assert_array_equal(expand_left(np.array([[v] for v in (0, 0, 16, 0, 0)]))[:, 0], V_LINEAR)
        np.testing.assert_array_equal(expand_left(np.array([[0, 0, 16, 0, 0]]))[0], H_LINEAR)

    def test_constant_and_rectangular_ramp(self):
        self.assert_expansion([[37]])
        self.assert_expansion([[37]*4 for _ in range(3)])
        self.assert_expansion([[100+8*x+16*y for x in range(4)] for y in range(3)])

    def test_asymmetric_nonmonotonic_plane_and_all_strip_parities(self):
        plane = [[9, 17, 3, 800], [100, 7, 1023, 71], [64, 900, 300, 4], [17, 63, 89, 777]]
        for start, stop in ((0, 8), (0, 1), (1, 7), (3, 4), (7, 8), (2, 6)):
            with self.subTest(start=start, stop=stop):
                self.assert_expansion(plane, start, stop)

    def test_explicit_replicated_boundary(self):
        np.testing.assert_array_equal(expand_left(np.array([[0, 8], [16, 24]])),
                                      [[0, 4, 8, 8], [4, 8, 12, 12], [12, 16, 20, 20], [16, 20, 24, 24]])


@unittest.skipIf(np is None, "NumPy required for experimental geometry checks")
class CandidateGeometryTests(unittest.TestCase):
    OPTIONS = (("linear-left", "linear", 0), ("cubic-left", "cubic", 0),
               ("linear-top-control", "linear", F(1, 2)),
               ("linear-bottom-control", "linear", F(-1, 2)))

    def test_each_candidate_matches_independent_exact_oracle(self):
        plane = [[9, 17, 3, 800], [100, 7, 1023, 71], [64, 900, 300, 4], [17, 63, 89, 777]]
        for variant, kernel, dy in self.OPTIONS:
            for start, stop in ((0, 8), (0, 1), (1, 7), (3, 4), (7, 8), (2, 6)):
                with self.subTest(variant=variant, start=start, stop=stop):
                    expected = np.array(expand(plane, kernel, dy=dy, start=start, stop=stop,
                                               horizontal_kernel="linear"), dtype=float)
                    actual = candidate_expand(np.array(plane, dtype=np.uint16), start, stop, variant)
                    np.testing.assert_array_equal(actual, expected)

    def test_cubic_has_expected_quarter_row_impulse_and_no_clamp(self):
        plane = np.array([[value]*3 for value in (0, 0, 16, 0, 0)], dtype=np.uint16)
        actual = candidate_expand(plane, variant="cubic-left")
        np.testing.assert_array_equal(actual[:, 2], np.array(V_CUBIC, dtype=float))
        self.assertLess(actual.min(), 0)

    def test_every_candidate_preserves_the_same_horizontal_impulse(self):
        plane = np.array([[0, 0, 16, 0, 0]]*5)
        for variant, _, _ in self.OPTIONS:
            with self.subTest(variant=variant):
                np.testing.assert_array_equal(candidate_expand(plane, variant=variant),
                                              np.array([H_LINEAR]*10))

    def test_constant_preserved_at_all_edges(self):
        for variant, _, _ in self.OPTIONS:
            for shape in ((1, 1), (3, 4)):
                np.testing.assert_array_equal(candidate_expand(np.full(shape, 37), variant=variant),
                                              np.full((shape[0]*2, shape[1]*2), 37.))

    def test_wrong_phase_controls_have_literal_distinct_ramps(self):
        plane = np.array([[0, 0], [16, 16], [32, 32]])
        for variant, vertical in (("linear-left", [0, 4, 12, 20, 28, 32]),
                                  ("linear-top-control", [0, 8, 16, 24, 32, 32]),
                                  ("linear-bottom-control", [0, 0, 8, 16, 24, 32])):
            np.testing.assert_array_equal(candidate_expand(plane, variant=variant)[:, 0], vertical)


if __name__ == "__main__":
    unittest.main()
