from dataclasses import FrozenInstanceError
from fractions import Fraction
import itertools
import math
import unittest

import colour_stage as stage
from known_answers import COLOUR_INPUTS, identity_source_transport, pq_decode_unit, pq_encode_unit

try:
    import numpy as np
except ImportError:
    np = None

IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
TARGET_YCC = ((8194/8192, 799/8192, 1681/8192),
              (8194/8192, -933/8192, 1091/8192),
              (8194/8192, 267/8192, -5545/8192))
TARGET_LMS = ((17080/16384, -348/16384, -348/16384),
              (-348/16384, 17080/16384, -348/16384),
              (-348/16384, -348/16384, 17080/16384))
EXTEND = "extend-positive-negative-to-zero"
UNIT = "reject-outside-unit"


def dm_identity():
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
              signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
              signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 8192 if i % 4 == 0 else 0
        dm[f"rgb_to_lms_coef{i}"] = 16384 if i % 4 == 0 else 0
    for i in range(3):
        dm[f"ycc_to_rgb_offset{i}"] = 0
    return dm


def config(dm=None, policy=EXTEND):
    return stage.ColourConfig.from_dm(dm_identity() if dm is None else dm,
        target_ycc=TARGET_YCC, target_lms=TARGET_LMS, target_offset=(0, .5, .5),
        pq_policy=policy, code_scale=4096)


class ColourStageTests(unittest.TestCase):
    def test_pq_high_precision_unit_answers(self):
        for value in (Fraction(0), Fraction(1, 1000000), Fraction(1, 100), Fraction(1, 2), Fraction(1)):
            self.assertAlmostEqual(stage.pq_encode(value, policy=UNIT), float(pq_encode_unit(value)), delta=2e-13)
            self.assertAlmostEqual(stage.pq_decode(value, policy=UNIT), float(pq_decode_unit(value)), delta=2e-13)

    def test_explicit_domain_policies_and_pole(self):
        for function in (stage.pq_decode, stage.pq_encode):
            for value in (-1, 1.2):
                with self.assertRaises(ValueError): function(value, policy=UNIT)
            self.assertEqual(function(-1, policy=EXTEND), function(0, policy=EXTEND))
            for value in (True, math.nan, math.inf, "0.5"):
                with self.assertRaises(ValueError): function(value, policy=EXTEND)
            with self.assertRaises(ValueError): function(.5, policy="implicit")
        with self.assertRaises(ValueError): stage.pq_decode(100, policy=EXTEND)
        self.assertGreater(stage.pq_decode(1.2, policy=EXTEND), 1)
        self.assertGreater(stage.pq_encode(1.2, policy=EXTEND), 1)

    def test_transport_against_independent_decimal_oracle(self):
        cfg = config(policy=UNIT)
        for name, values in COLOUR_INPUTS.items():
            with self.subTest(name=name):
                self.assertEqual(stage.convert_sample(values, cfg).codes, identity_source_transport(values))

    def test_no_hidden_source_upper_bound_or_rgb_limit(self):
        dm = dm_identity()
        for index in (0, 4, 8): dm[f"ycc_to_rgb_coef{index}"] *= 2
        result = stage.convert_sample((3000, 3000, 3000), config(dm))
        self.assertGreater(max(result.source_nonlinear), 1)
        self.assertGreater(max(result.common_linear_lms), 1)
        with self.assertRaises(ValueError): stage.convert_sample((3000, 3000, 3000), config(dm, UNIT))

    def test_validation_immutable_copy_and_singular_target(self):
        matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        cfg = stage.ColourConfig(matrix, [0, 0, 0], matrix, matrix, [0, 0, 0], matrix, UNIT, 4096)
        matrix[0][0] = 0
        self.assertEqual(cfg.source_ycc, IDENTITY)
        with self.assertRaises(FrozenInstanceError): cfg.pq_policy = EXTEND
        for target in (((0, 0, 0),)*3, ((1, 0, 0),)*3, ((math.nan, 0, 0), (0, 1, 0), (0, 0, 1))):
            with self.assertRaises(ValueError):
                stage.ColourConfig(IDENTITY, (0, 0, 0), IDENTITY, target, (0, 0, 0), IDENTITY, UNIT, 4096)
        for key, value in (("compressed", 0), ("signal_bit_depth", True),
                           ("signal_bit_depth", 10), ("ycc_to_rgb_coef0", 8192.0),
                           ("ycc_to_rgb_offset0", math.inf)):
            dm = dm_identity(); dm[key] = value
            with self.assertRaises(ValueError): config(dm)
        with self.assertRaises(TypeError): stage.ColourConfig.from_dm(dm_identity())

    def test_nonsymmetric_inverse_and_final_only_target_bound(self):
        target = ((1, 2, 0), (0, 1, 3), (0, 0, 1))
        cfg = stage.ColourConfig(IDENTITY, (0, 0, 0), IDENTITY, target,
                                 (0, 0, 0), IDENTITY, UNIT, 4096)
        self.assertEqual(cfg.target_ycc_inverse, ((1, -2, 6), (0, 1, -3), (0, 0, 1)))
        result = stage.convert_sample((0, 4095, 0), cfg)
        self.assertLess(result.transport_before_quantization[0], -1.9)
        self.assertEqual(result.codes, (0, 4095, 0))
        for scale in (True, 4096.0, 4095):
            with self.assertRaises(ValueError):
                stage.ColourConfig(IDENTITY, (0, 0, 0), IDENTITY, target,
                                   (0, 0, 0), IDENTITY, UNIT, scale)

    def test_invalid_samples_and_lazy_conversion(self):
        cfg = config()
        for values in ((0, 0), (0, 0, 0, 0), (True, 0, 0), (-1, 0, 0),
                       (4096, 0, 0), (math.inf, 0, 0)):
            with self.assertRaises(ValueError): stage.convert_sample(values, cfg)
        seen = []
        def values():
            for value in ((2048, 2048, 2048), (4096, 0, 0)):
                seen.append(value); yield value
        converted = stage.iter_converted(values(), cfg)
        self.assertEqual(seen, [])
        self.assertEqual(next(converted).codes, identity_source_transport((2048, 2048, 2048)))
        self.assertEqual(len(seen), 1)
        with self.assertRaises(ValueError): next(converted)
        self.assertEqual(len(list(itertools.islice(stage.iter_converted(itertools.repeat((0, 0, 0)), cfg), 10))), 10)

    @unittest.skipIf(np is None, "NumPy required for older diagnostic comparison")
    def test_numpy_diagnostic_comparison_nonidentity_matrices(self):
        from output_frame import convert
        samples = [(n*17 % 4096, n*31 % 4096, n*47 % 4096) for n in range(256)]
        samples += list(COLOUR_INPUTS.values())
        for variant in range(3):
            dm = dm_identity()
            if variant == 1:
                dm["ycc_to_rgb_coef1"] = -512
                dm["rgb_to_lms_coef3"] = 256
                dm["ycc_to_rgb_offset0"] = 1 << 24
            elif variant == 2:
                dm["ycc_to_rgb_coef0"] = 12000
                dm["rgb_to_lms_coef1"] = -128
            old_stages = {}
            old = convert(np.array([samples]), dm, "direct", lambda n, a: old_stages.update({n: a}))
            cfg = config(dm)
            for index, sample in enumerate(samples):
                result = stage.convert_sample(sample, cfg)
                self.assertEqual(result.codes, tuple(int(v) for v in old[0, index]))
                for name in ("source_nonlinear", "common_linear_lms", "target_linear", "transport_before_quantization"):
                    for actual, expected in zip(getattr(result, name), old_stages[name][0, index]):
                        self.assertTrue(math.isclose(actual, float(expected), rel_tol=2e-11, abs_tol=2e-12), (name, actual, expected))


if __name__ == "__main__":
    unittest.main()
