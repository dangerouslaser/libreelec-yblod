import json
import unittest
from unittest.mock import patch

import numpy as np

import chroma_geometry
from chroma_geometry import VARIANTS, configuration, expand
from output_frame import expand_left


class ChromaGeometryImplementationTest(unittest.TestCase):
    def test_linear_baseline_matches_existing_exactly_for_every_strip(self):
        rng = np.random.default_rng(721)
        for dtype in (np.uint16, np.int64, np.float32, np.float64):
            values = rng.integers(0, 4096, (37, 11)).astype(dtype)
            for start, stop in ((0, 74), (1, 33), (17, 68), (73, 74), (3, 3)):
                result = expand(values, start, stop)
                expected = expand_left(values, start, stop)
                self.assertEqual(result.dtype, np.float64)
                self.assertEqual(result.tobytes(), expected.tobytes())

    def test_strip_concatenation_and_internal_chunk_sizes_are_identical(self):
        values = np.random.default_rng(931).integers(0, 4096, (36, 9), dtype=np.uint16)
        for variant in VARIANTS:
            expected = expand(values, variant=variant)
            actual = np.concatenate([expand(values, a, b, variant) for a, b in ((0, 1), (1, 30), (30, 47), (47, 72))])
            self.assertEqual(actual.tobytes(), expected.tobytes())
            for rows in (1, 7, 32, 128):
                with patch("chroma_geometry.WORK_ROWS", rows):
                    self.assertEqual(expand(values, variant=variant).tobytes(), expected.tobytes())

    def test_constant_single_pixel_and_readonly_strided_planes(self):
        for variant in VARIANTS:
            np.testing.assert_array_equal(expand(np.array([[512]], dtype=np.uint16), variant=variant),
                                          np.full((2, 2), 512.0))
            values = np.arange(300, dtype=np.float64).reshape(30, 10)[::2, ::2]
            original = values.copy()
            values.flags.writeable = False
            self.assertTrue(np.all(np.isfinite(expand(values, 1, 17, variant))))
            np.testing.assert_array_equal(values, original)

    def test_cubic_overshoot_is_not_clipped_or_rounded(self):
        values = np.repeat(np.array([0, 0, 1023, 1023], dtype=np.uint16)[:, None], 2, axis=1)
        result = expand(values, variant="cubic-left")
        self.assertLess(result.min(), 0)
        self.assertGreater(result.max(), 1023)
        self.assertTrue(np.any(result != np.floor(result)))

    def test_only_requested_rows_are_converted_to_float64(self):
        values = np.ones((200, 7), dtype=np.uint16)
        original = chroma_geometry._samples
        requested = []

        def checked_samples(a, indices):
            self.assertIs(a, values)
            self.assertLessEqual(len(indices), chroma_geometry.WORK_ROWS)
            requested.extend(indices.tolist())
            return original(a, indices)

        for variant in VARIANTS:
            with patch("chroma_geometry._samples", side_effect=checked_samples):
                expand(values, 151, 188, variant)
        self.assertGreater(min(requested), 0)
        self.assertLess(max(requested), values.shape[0] - 1)

    def test_invalid_inputs_bounds_and_nonfinite_samples_rejected(self):
        for values in (np.ones(3), np.ones((0, 2)), np.ones((2, 2), dtype=bool),
                       np.ones((2, 2), dtype=complex), [[1, 2]]):
            with self.assertRaises(ValueError):
                expand(values)
        values = np.ones((3, 2))
        for start, stop in ((-1, 1), (1, 7), (3, 2), (0.5, 3), (False, 2)):
            with self.assertRaises(ValueError):
                expand(values, start, stop)
        with self.assertRaises(ValueError):
            expand(values, variant="invented")
        values[1, 1] = np.nan
        with self.assertRaises(ValueError):
            expand(values)
        values[1, 1] = np.inf
        with self.assertRaises(ValueError):
            expand(values, variant="cubic-left")

    def test_configuration_is_independent_json_safe_and_labels_controls(self):
        for variant in VARIANTS:
            config = configuration(variant)
            json.dumps(config, allow_nan=False)
            self.assertEqual(config["invalid_geometry_control"], variant.endswith("control"))
            self.assertFalse(config["production_choice"])
            self.assertTrue(config["horizontal"]["unchanged_from_output_frame_expand_left"])
            config["horizontal"]["offsets"].append(99)
            self.assertEqual(configuration(variant)["horizontal"]["offsets"], [0, 1])


if __name__ == "__main__":
    unittest.main()
