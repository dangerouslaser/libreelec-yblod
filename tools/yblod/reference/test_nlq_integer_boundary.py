"""Independent exact rounding boundaries; no hardware, moviepixels or policychoice."""
from fractions import Fraction as F
import unittest

import nlq_integer_boundary as boundary


class IntegerBoundaryTests(unittest.TestCase):
    def test_policy_ties_above_and_below_neutral(self):
        expected={"floor":(511,512),"nearest-half-up":(512,513),"nearest-ties-even":(512,512)}
        for policy,answers in expected.items():
            self.assertEqual((boundary.quantize(511*64+32,policy),boundary.quantize(512*64+32,policy)),answers)
        self.assertEqual([boundary.quantize(32767,p) for p in boundary.POLICIES],[511,512,512])
        self.assertEqual([boundary.quantize(32768,p) for p in boundary.POLICIES],[512,512,512])
        self.assertEqual([boundary.quantize(32769,p) for p in boundary.POLICIES],[512,512,512])

    def test_all_native_anchors_equal_unchanged_reference(self):
        for native in range(1024):
            # Independently simplified declaredfixture arithmetic on integers.
            distance=native-512
            expected=0 if distance==0 else 16*distance-8*(1 if distance>0 else -1)
            for policy in boundary.POLICIES:
                row=boundary.evaluate(native*64,policy)
                self.assertEqual(row["quantized_native_code"],native)
                self.assertEqual(row["integer_reference_residual"],expected)
                self.assertEqual(row["hypothetical_unquantized_formula_residual"],[expected,1])
                self.assertEqual(row["synthetic_reconstructed_12bit"],(32768+expected+8)//16)

    def test_quantizer_stored_word_candidates_and_strict_domain_are_separate(self):
        for p in boundary.POLICIES:
            self.assertEqual(boundary.quantize(65472,p),1023)
            with self.assertRaises(ValueError):boundary.quantize(65503,p)
            self.assertEqual(boundary.candidate(65503,p),{"native_code":1023,"in_domain":True})
        for raw in (65504,65535):
            self.assertEqual(boundary.candidate(raw,"floor"),{"native_code":1023,"in_domain":True})
            for policy in boundary.POLICIES[1:]:self.assertEqual(boundary.candidate(raw,policy),{"native_code":1024,"in_domain":False})

    def test_invalid_inputs_never_clamp_or_accept_float_bool(self):
        for raw in (-1,65473,65535,65536,False,1.0,F(1)):
            for policy in boundary.POLICIES:
                with self.assertRaises(ValueError):boundary.quantize(raw,policy)
        with self.assertRaises(ValueError):boundary.quantize(32768,"pick-best")

    def test_dense_neutral_suppression_exact_spans_and_monotonicity(self):
        spans={"floor":(32768,32831,64),"nearest-half-up":(32736,32799,64),"nearest-ties-even":(32736,32800,65)}
        for policy,expected in spans.items():
            scope=boundary._scope(boundary.neutral_words(),policy)
            span=scope["zero_residual_span"]
            self.assertEqual((span["first_raw_word"],span["last_raw_word"],span["sampled_zero_count"]),expected)
            self.assertTrue(span["every_raw_word_in_span_sampled_zero"])
            self.assertEqual(scope["monotonicity_decreases"]["integer_residual"],0)
            self.assertEqual(scope["monotonicity_decreases"]["reconstructed12"],0)
            self.assertEqual(scope["sign_checks"]["integer_residual_wrong_sign_vs_raw_sample"],0)
            self.assertEqual(scope["monotonicity_decreases"]["hypothetical_unquantized_formula"],2)
            self.assertEqual(scope["sign_checks"]["hypothetical_formula_wrong_sign_vs_raw_sample"],62)

    def test_neutral_fractional_formula_extension_label_and_values_not_integer_rule(self):
        below=boundary.evaluate(32767,"nearest-half-up");above=boundary.evaluate(32769,"nearest-half-up")
        self.assertEqual(below["integer_reference_residual"],0);self.assertEqual(above["integer_reference_residual"],0)
        self.assertEqual(below["hypothetical_unquantized_formula_residual"],[31,4])
        self.assertEqual(above["hypothetical_unquantized_formula_residual"],[-31,4])

    def test_report_hashes_reproducible_and_histogram_counts(self):
        first=boundary.report();second=boundary.report();self.assertEqual(first,second)
        self.assertEqual(len(boundary.whole_words()),4093);self.assertEqual(len(boundary.neutral_words()),257)
        for policy,scopes in first["policies"].items():
            for scope in scopes.values():
                self.assertEqual(sum(row["count"] for row in scope["native_quantization_bias_histogram"]),scope["samples"])
                self.assertEqual(sum(row["count"] for row in scope["residual_error_histogram_vs_hypothetical_formula"]),scope["samples"])
        self.assertTrue(first["integer_anchor_checks"]["all_policies_equal_native_anchors"])


if __name__=="__main__":unittest.main()
