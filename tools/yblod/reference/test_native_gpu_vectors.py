"""Independent CPU/oracle baseline for future GPU differential fixtures."""
import tempfile
from pathlib import Path
import unittest

import native_stage
from native_gpu_vectors import vector_fixtures, expected_stages, width_oracle, WIDTH_LIMIT


class GPUVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.library = native_stage.build(Path(cls.temporary.name)/"build")

    def test_every_four_stage_matches_native_cpu_even_width_rejected(self):
        fixtures = vector_fixtures()
        self.assertEqual(len({v.name for v in fixtures}), len(fixtures))
        for vector in fixtures:
            with self.subTest(vector=vector.name):
                engine = native_stage.NativeStage(self.library, vector.mapping,
                    None if vector.nlq is None else (vector.nlq,)*3, vector.output_depth,
                    disabled=vector.nlq is None)
                actual = engine.process(vector.component, vector.triplets, vector.el_samples)
                self.assertEqual(tuple(tuple(actual[name]) for name in
                    ("mapped", "residual", "sum", "reconstructed")), expected_stages(vector))

    def test_literal_pivot_and_signed_floor_known_answers(self):
        cases = {v.name: v for v in vector_fixtures()}
        self.assertEqual(expected_stages(cases["right-owned-pivots"])[0],
                         (4096, 4096, 4096, 4096, 8192, 8192, 16384, 16384, 16384, 16384))
        self.assertEqual(expected_stages(cases["negative-cap-before-floor"]),
                         ((32,)*5, (-9, -8, 0, 8, 8), (23, 24, 32, 40, 40), (1, 2, 2, 3, 3)))

    def test_width_boundary_expected_rejection_is_explicit(self):
        cases = {v.name: v for v in vector_fixtures()}
        for bound in (WIDTH_LIMIT-1, WIDTH_LIMIT, WIDTH_LIMIT+1):
            result = width_oracle(cases[f"mmr-width-{bound}"].mapping)
            self.assertEqual(result, dict(supported=bound <= WIDTH_LIMIT, mmr_segment_count=1,
                worst_l1_bound=bound, first_unsupported=(-1, -1) if bound <= WIDTH_LIMIT else (1, 0)))

    def test_negative_floor_identity_including_int64_min(self):
        # This establishes the exact shader helper contract. Neither negative
        # arithmetic shifts nor division truncation are accepted substitutes.
        values = tuple(range(-128, 129)) + (-2**63, -2**63+1, 2**63-1)
        for shift in range(37):
            for value in values:
                positive_shift_only = value >> shift if value >= 0 else -1-((-(value+1)) >> shift)
                self.assertEqual(positive_shift_only, value // (1 << shift))


if __name__ == "__main__":
    unittest.main()
