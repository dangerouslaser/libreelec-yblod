"""Independent native-phase geometry, rounding, edge and order checks.

No movie pixels, fitted weights or hardware captures supply expected answers.
These test the stated experiment, not a Dolby conformance specification.
"""
from fractions import Fraction as F
import unittest

from preparation_oracle import annex_chroma_physical_y, native_phase, point, round_half_up

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    from prepare_frame import chroma_to_left


class PreparationPointTests(unittest.TestCase):
    def test_cubic_quarter_point_from_endpoint_constraints(self):
        # One nonzero endpoint at a time yields the literal four point values.
        # Expected values were derived at t=1/4, not read from production taps.
        expected = (F(-9, 128), F(111, 128), F(29, 128), F(-3, 128))
        for impulse, answer in enumerate(expected):
            column = [int(i == impulse) for i in range(4)]
            self.assertEqual(point(column, F(5, 4), "cubic128"), answer)

    def test_constant_is_preserved_at_replicated_edges(self):
        for method in ("linear", "cubic128"):
            for value in (0, 1, 512, 1023):
                for shape in ((1, 1), (7, 3)):
                    rows = [[value]*shape[1] for _ in range(shape[0])]
                    actual, stats = native_phase(rows, method)
                    self.assertEqual(actual, rows)
                    self.assertEqual(stats["below_zero_before_bound"], 0)
                    self.assertEqual(stats["above_maximum_before_bound"], 0)

    def test_literal_ramp_and_edge_values(self):
        rows = [[value] for value in (100, 228, 356, 484, 612, 740)]
        self.assertEqual(native_phase(rows, "linear")[0], [[v] for v in (132, 260, 388, 516, 644, 740)])
        self.assertEqual(native_phase(rows, "cubic128")[0], [[v] for v in (123, 260, 388, 516, 647, 749)])
        # Interior phase is+1/4 native chroma row, not+1/2.
        for method in ("linear", "cubic128"):
            self.assertEqual(point([100, 228, 356, 484, 612], F(9, 4), method), 388)

    def test_literal_center_impulse_including_negative_lobes(self):
        rows = [[512+128*int(y == 3)] for y in range(7)]
        self.assertEqual(native_phase(rows, "linear")[0], [[v] for v in (512, 512, 544, 608, 512, 512, 512)])
        self.assertEqual(native_phase(rows, "cubic128")[0], [[v] for v in (512, 509, 541, 623, 503, 512, 512)])

    def test_literal_first_and_last_impulse_edges(self):
        first = [[640]]+[[512] for _ in range(6)]
        last = [[512] for _ in range(6)]+[[640]]
        self.assertEqual(native_phase(first, "cubic128")[0], [[v] for v in (614, 503, 512, 512, 512, 512, 512)])
        self.assertEqual(native_phase(last, "cubic128")[0], [[v] for v in (512, 512, 512, 512, 509, 538, 649)])

    def test_exact_halfway_rounding_including_negative_lobes(self):
        self.assertEqual(round_half_up(F(1, 2)), 1)
        self.assertEqual(round_half_up(F(-1, 2)), 0)
        self.assertEqual(round_half_up(F(-9, 2)), -4)
        self.assertEqual(point([0, 0, 64, 0], F(5, 4), "cubic128"), F(29, 2))
        self.assertEqual(native_phase([[0], [0], [64], [0]], "cubic128")[0][1][0], 15)
        self.assertEqual(native_phase([[0], [2]], "linear")[0][0][0], 1)

    def test_round_then_native_bounds_are_explicit(self):
        values, stats = native_phase([[0], [0], [1023], [1023]], "cubic128")
        self.assertEqual(values, [[0], [208], [1023], [1023]])
        self.assertEqual(stats, {"below_zero_before_bound": 1, "above_maximum_before_bound": 1,
                                 "unbounded_minimum": -24, "unbounded_maximum": 1095})

    def test_columns_are_independent_and_horizontal_phase_is_unchanged(self):
        rows = [[100+128*y, 900-100*y, 17] for y in range(6)]
        for method in ("linear", "cubic128"):
            expanded, _ = native_phase(rows, method)
            for x in range(3):
                separate, _ = native_phase([[row[x]] for row in rows], method)
                self.assertEqual([row[x] for row in expanded], [row[0] for row in separate])
            self.assertEqual([row[2] for row in expanded], [17]*6)

    def test_native_shift_cannot_be_moved_after_2x_at_same_numeric_phase(self):
        for k in range(8):
            desired_left = 2*k+F(1, 2)
            self.assertEqual(annex_chroma_physical_y(k), desired_left)
            self.assertEqual(annex_chroma_physical_y(k, native_shift=0), 2*k-F(1, 2))
            self.assertEqual(annex_chroma_physical_y(k, native_shift=0, post_shift=F(1, 4)), 2*k)
            self.assertEqual(annex_chroma_physical_y(k, native_shift=0, post_shift=F(1, 2)), desired_left)
        # Matching coordinates alone does not equate two cascaded filters or
        # their intermediate rounding/edge handling. No order variant is run.


@unittest.skipIf(np is None, "NumPy required for native preparation implementation checks")
class PreparationImplementationTests(unittest.TestCase):
    def test_each_filter_against_independent_point_polynomial(self):
        rows = [[(73*y*y+211*x+17*x*y)%1024 for x in range(5)] for y in range(67)]
        for method in ("linear", "cubic128"):
            expected, stats = native_phase(rows, method)
            source = np.array(rows, dtype=np.uint16)
            source.flags.writeable = False
            actual, measured = chroma_to_left(source, "topleft", 10, method)
            np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(source, rows)
            for key, value in stats.items():
                self.assertEqual(measured[key], value)

    def test_literal_bound_events_and_halfway_sample(self):
        actual, stats = chroma_to_left(np.array([[0], [0], [1023], [1023]]), "topleft", 10, "cubic128")
        np.testing.assert_array_equal(actual, [[0], [208], [1023], [1023]])
        self.assertEqual((stats["below_zero_before_bound"], stats["above_maximum_before_bound"]), (1, 1))
        self.assertEqual((stats["unbounded_minimum"], stats["unbounded_maximum"]), (-24, 1095))
        actual, _ = chroma_to_left(np.array([[0], [0], [64], [0]]), "topleft", 10, "cubic128")
        self.assertEqual(int(actual[1, 0]), 15)

    def test_left_input_is_identity_for_both_candidate_methods(self):
        source = np.array([[10, 100, 900], [1000, 50, 300]], dtype=np.uint16)
        for method in ("linear", "cubic128"):
            actual, operation = chroma_to_left(source, "left", 10, method)
            np.testing.assert_array_equal(actual, source)
            self.assertEqual(operation["operation"], "identity")


if __name__ == "__main__":
    unittest.main()
