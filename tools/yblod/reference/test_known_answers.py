"""Known answers independent of captured hardware and production helpers.

Run with: python3 -m unittest -v test_known_answers
NumPy is optional for the scalar/bundle tests; colour tests explicitly skip
when absent. A release check must run these with requirements.txt installed.
"""
import copy
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import struct
import tempfile
import unittest

from known_answers import (COLOUR_INPUTS, identity_source_transport,
                           pq_decode_unit, pq_encode_unit, solve3)
from reference import inverse_el, polynomial, reconstruct, run

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    from output_frame import convert, pq_decode, pq_encode


# Fixed fixtures, not produced by the implementation or loaded from captures.
# The separate scalar oracle documents/rechecks how they were derived.
TRANSPORT_ANSWERS = {
    "black": (0, 2048, 2048),
    "dark_neutral": (256, 2048, 2048),
    "mid_neutral": (2048, 2048, 2048),
    "bright_neutral": (4094, 2048, 2048),
    "source_primary_1": (1263, 4095, 3080),
    "source_primary_2": (1263, 0, 2505),
    "source_primary_3": (1007, 2555, 559),
    "unequal_channels": (979, 484, 1169),
}


def source_dm():
    """Synthetic identity metadata; no import from the implementation/tests."""
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
              signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
              signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 8192 if i in (0, 4, 8) else 0
        dm[f"rgb_to_lms_coef{i}"] = 16384 if i in (0, 4, 8) else 0
    for i in range(3):
        dm[f"ycc_to_rgb_offset{i}"] = 0
    return dm


class ScalarOracleTests(unittest.TestCase):
    def test_pq_published_domain_anchors(self):
        # Rounded numerical anchors, not roundtrips. The published standard
        # specifies equations; these decimal approximations are test fixtures.
        anchors = (("0", "0.0000007309559025783966"),
                   ("0.0001", "0.1499457321"),
                   ("0.01", "0.5080784215"),
                   ("0.1", "0.7518270962"),
                   ("1", "1"))
        for linear, encoded in anchors:
            with self.subTest(linear=linear):
                self.assertLess(abs(pq_encode_unit(Decimal(linear)) - Decimal(encoded)), Decimal("5e-11"))
        self.assertEqual(pq_decode_unit(0), 0)
        self.assertEqual(pq_decode_unit(1), 1)

    def test_oracle_refuses_to_choose_extended_pq_policy(self):
        for function in (pq_encode_unit, pq_decode_unit):
            for value in (Fraction(-1, 100), Fraction(101, 100)):
                with self.assertRaises(ValueError):
                    function(value)

    def test_separate_matrix_solver_known_result(self):
        # 2*3+4=10; 3+3*4+5=20; 4+2*5=14.
        self.assertEqual(solve3(((2, 1, 0), (1, 3, 1), (0, 1, 2)),
                                [Decimal(10), Decimal(20), Decimal(14)]),
                         [Decimal(3), Decimal(4), Decimal(5)])

    def test_fixed_colour_fixtures_against_decimal_oracle(self):
        for name, codes in COLOUR_INPUTS.items():
            with self.subTest(name=name):
                self.assertEqual(identity_source_transport(codes), TRANSPORT_ANSWERS[name])

    def test_nontrivial_polynomial_against_rational_equation(self):
        # f(x)=1/8+x/2+x*x/4, independently evaluated as a rational number.
        # This tests every input code, not only an identity or roundtrip.
        for sample in range(1024):
            x = Fraction(sample, 1024)
            exact = (Fraction(1, 8) + x/2 + x*x/4) * 65536
            self.assertEqual(polynomial(sample, [131072, 524288, 262144], 10, 20),
                             exact.numerator // exact.denominator)

    def test_residual_half_steps_sign_threshold_and_limit(self):
        parameters = dict(offset=512, slope=512, threshold=128, maximum=1024)
        # Before /32: +/- (512 + 256), +/- (1536 + 256), then saturation +/-2048.
        for sample, answer in ((512, 0), (513, 24), (511, -24),
                               (514, 56), (510, -56), (515, 64), (509, -64)):
            self.assertEqual(inverse_el(sample, parameters, 10, 20), answer)

    def test_rounding_halfway_and_both_bounds_fixed_answers(self):
        # Halfway ties go toward positive infinity, including signed sums.
        vectors = ((0, 7, 0), (0, 8, 1), (16, -8, 1), (16, -9, 0),
                   (160, -80, 5), (0, -9, 0), (65535, 0, 4095),
                   (65535, -24, 4094), (65535, 80, 4095))
        for mapped, residual, expected in vectors:
            with self.subTest(mapped=mapped, residual=residual):
                self.assertEqual(reconstruct(mapped, residual, 12), expected)


class SyntheticBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        identity = dict(frame_id="independent-vector-0", pts=0, time_base=[1, 24])
        mapping = {"pivots": [0, 1023], "segments": [
            {"method": "polynomial", "coefficients": [0, 1048576]}]}
        self.manifest = {
            "schema": "yblod.composer-frame.v1", "width": 8, "height": 2,
            "format": "yuv420p-u16le-lsb", "transfer": "pq", "chroma_location": "left",
            "preparation": "Synthetic aligned layer samples; no spatial filtering involved.",
            "bl": dict(identity, planes={c: "bl_"+c for c in ("Y", "Cb", "Cr")}),
            "el": dict(identity, planes={c: "el_"+c for c in ("Y", "Cb", "Cr")}),
            "metadata": dict(identity, bl_bit_depth=10, el_bit_depth=10, output_bit_depth=12,
                             coefficient_log2_denom=20, disable_residual=False,
                             mappings=[copy.deepcopy(mapping) for _ in range(3)],
                             nlq_method="linear_deadzone", nlq=[dict(offset=512, slope=512,
                                                                       threshold=0, maximum=4096)
                                                                for _ in range(3)])}
        self.planes = {"bl_Y": [0, 0, 0, 100, 100, 1023, 1023, 1]*2,
                       "el_Y": [512, 513, 511, 514, 510, 1023, 0, 512]*2,
                       "bl_Cb": [0, 256, 512, 1023], "el_Cb": [513, 511, 1023, 0],
                       "bl_Cr": [1023, 512, 256, 0], "el_Cr": [512]*4}

    def compose(self):
        for name, values in self.planes.items():
            (self.root/name).write_bytes(struct.pack("<"+"H"*len(values), *values))
        path = self.root/"frame.json"
        path.write_text(json.dumps(self.manifest))
        return run(path, self.root/"result")

    def values(self, stage, count, kind="H"):
        suffix = "i32le" if kind == "i" else "u16le"
        return struct.unpack("<"+kind*count, (self.root/"result"/(stage+"."+suffix)).read_bytes())

    def test_controlled_layer_contributions_and_final_bounds(self):
        self.compose()
        self.assertEqual(self.values("residual_Y", 16, "i"),
                         (0, 16, -16, 48, -48, 256, -256, 0)*2)
        self.assertEqual(self.values("reconstructed_Y", 16),
                         (0, 1, 0, 403, 397, 4095, 4076, 4)*2)
        self.assertEqual(self.values("reconstructed_Cb", 4), (1, 1023, 2064, 4076))
        self.assertEqual(self.values("reconstructed_Cr", 4), (4092, 2048, 1024, 0))

    def test_disabled_layer_is_exact_base_mapping_even_if_el_nonzero(self):
        self.manifest["metadata"]["disable_residual"] = True
        report = self.compose()
        self.assertEqual(self.values("reconstructed_Y", 16), (0, 0, 0, 400, 400, 4092, 4092, 4)*2)
        for channel, count in (("Y", 16), ("Cb", 4), ("Cr", 4)):
            self.assertEqual(self.values("residual_"+channel, count, "i"), (0,)*count)
        self.assertFalse(any(name.startswith("el_") for name in report["input_sha256"]))

    def test_neutral_layer_is_exact_base_mapping(self):
        for name in ("el_Y", "el_Cb", "el_Cr"):
            self.planes[name] = [512]*len(self.planes[name])
        self.compose()
        self.assertEqual(self.values("reconstructed_Y", 16), (0, 0, 0, 400, 400, 4092, 4092, 4)*2)
        self.assertEqual(self.values("reconstructed_Cb", 4), (0, 1024, 2048, 4092))

    def test_quadratic_full_bundle_fixed_codes(self):
        self.manifest["metadata"]["disable_residual"] = True
        self.manifest["metadata"]["mappings"][0]["segments"][0]["coefficients"] = [131072, 524288, 262144]
        self.planes["bl_Y"] = [0, 256, 512, 768]*4
        self.compose()
        self.assertEqual(self.values("mapped_Y", 16), (8192, 17408, 28672, 41984)*4)
        self.assertEqual(self.values("reconstructed_Y", 16), (512, 1088, 1792, 2624)*4)


@unittest.skipIf(np is None, "NumPy required for output implementation checks")
class OutputKnownAnswerTests(unittest.TestCase):
    def test_pq_float_implementation_against_high_precision_scalar(self):
        for value in (Fraction(0), Fraction(1, 1000000), Fraction(1, 10000),
                      Fraction(1, 100), Fraction(1, 10), Fraction(1)):
            encoded = float(pq_encode_unit(value))
            decoded = float(pq_decode_unit(value))
            self.assertAlmostEqual(float(pq_encode(np.array(float(value)))), encoded, delta=2e-13)
            self.assertAlmostEqual(float(pq_decode(np.array(float(value)))), decoded, delta=2e-13)

    def test_fixed_neutrals_and_source_primaries(self):
        for name, values in COLOUR_INPUTS.items():
            with self.subTest(name=name):
                actual = convert(np.array([[values]]), source_dm(), "direct", lambda *args: None)
                self.assertEqual(tuple(map(int, actual[0, 0])), TRANSPORT_ANSWERS[name])

    def test_in_domain_source_limiting_cannot_change_these_vectors(self):
        for name, values in COLOUR_INPUTS.items():
            with self.subTest(name=name):
                actual = convert(np.array([[values]]), source_dm(), "source-pq-bound-diagnostic", lambda *args: None)
                self.assertEqual(tuple(map(int, actual[0, 0])), TRANSPORT_ANSWERS[name])

    def test_nonidentity_source_matrix_offsets_and_order(self):
        dm = source_dm()
        # Subtract [1/16,1/2,1/2], then rows [2,0,1], [0,1,-1], [1,0,0].
        for i, value in enumerate((16384, 0, 8192, 0, 8192, -8192, 8192, 0, 0)):
            dm[f"ycc_to_rgb_coef{i}"] = value
        for i, value in enumerate((16777216, 134217728, 134217728)):
            dm[f"ycc_to_rgb_offset{i}"] = value
        # Permute the decoded channels. This detects applying the matrix on
        # nonlinear values, transposing it, or confusing either matrix scale.
        for i, value in enumerate((0, 16384, 0, 0, 0, 16384, 16384, 0, 0)):
            dm[f"rgb_to_lms_coef{i}"] = value
        stages = {}
        convert(np.array([[[768, 3072, 2304]]]), dm, "direct", lambda n, a: stages.update({n: a}))
        np.testing.assert_array_equal(stages["source_nonlinear"], [[[.3125, .1875, .125]]])
        expected = [float(pq_decode_unit(Fraction(3, 16))), float(pq_decode_unit(Fraction(1, 8))),
                    float(pq_decode_unit(Fraction(5, 16)))]
        np.testing.assert_allclose(stages["common_linear_lms"], [[expected]], rtol=1e-12, atol=1e-15)


if __name__ == "__main__":
    unittest.main()
