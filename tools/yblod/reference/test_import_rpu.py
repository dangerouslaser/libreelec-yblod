import copy
import unittest

from import_rpu import fixed, normalize


def synthetic_rpu():
    curve = {"num_pivots_minus2": 1, "pivots": [0, 512, 511], "mapping_idc": "Polynomial",
             "poly_order_minus1": [0, 0], "linear_interp_flag": [False, False],
             "poly_coef_int": [[0, 1], [0, 1]], "poly_coef": [[0, 0], [0, 0]]}
    return {"dovi_profile": 7, "el_type": "FEL", "header": {
        "use_prev_vdr_rpu_flag": False, "coefficient_data_type": 0, "rpu_type": 2, "rpu_format": 18,
        "vdr_rpu_normalized_idc": 1, "ext_mapping_idc_0_4": 0, "ext_mapping_idc_5_7": 0,
        "coefficient_log2_denom": 23, "coefficient_log2_denom_length": 23,
        "bl_bit_depth_minus8": 2, "el_bit_depth_minus8": 2, "vdr_bit_depth_minus8": 4,
        "disable_residual_flag": False}, "rpu_data_mapping": {
            "mapping_color_space": 0, "mapping_chroma_format_idc": 0,
            "num_x_partitions_minus1": 0, "num_y_partitions_minus1": 0,
            "curves": [copy.deepcopy(curve) for _ in range(3)], "nlq_method_idc": "LinearDeadzone",
            "nlq_num_pivots_minus2": 0, "nlq_pred_pivot_value": [0, 1023], "nlq": {
                "nlq_offset": [512] * 3, "vdr_in_max_int": [0] * 3, "vdr_in_max": [1048576] * 3,
                "linear_deadzone_slope_int": [0] * 3, "linear_deadzone_slope": [2048] * 3,
                "linear_deadzone_threshold_int": [0] * 3, "linear_deadzone_threshold": [0] * 3}}}


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.rpu = synthetic_rpu()
        self.identity = {"frame_id": "synthetic", "pts": 100, "time_base": [1, 1000]}

    def test_fixed_point_signed_integer_plus_unsigned_fraction(self):
        self.assertEqual(fixed(-1, 1 << 22, 23), -(1 << 22))
        with self.assertRaises(ValueError):
            fixed(0, 1 << 23, 23)
        with self.assertRaises(ValueError):
            fixed(0.0, 0, 23)

    def test_pivot_deltas_and_exact_coefficients(self):
        result = normalize(self.rpu, self.identity)
        self.assertEqual(result["mappings"][0]["pivots"], [0, 512, 1023])
        self.assertEqual(result["mappings"][0]["segments"][0]["coefficients"], [0, 8388608])
        self.assertEqual(result["nlq"][0], {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1048576})
        self.assertEqual(result["pts"], 100)

    def test_mmr_sign_and_shape(self):
        self.rpu["rpu_data_mapping"]["curves"][1] = {
            "num_pivots_minus2": 0, "pivots": [0, 1023], "mapping_idc": "MMR",
            "mmr_order_minus1": [0], "mmr_constant_int": [-1], "mmr_constant": [1 << 22],
            "mmr_coef_int": [[[-1, 0, 1, 0, 0, 0, 0]]],
            "mmr_coef": [[[1 << 22, 0, 0, 0, 0, 0, 0]]]}
        segment = normalize(self.rpu, self.identity)["mappings"][1]["segments"][0]
        self.assertEqual(segment["constant"], -(1 << 22))
        self.assertEqual(segment["coefficients"][0][:3], [-(1 << 22), 0, 1 << 23])

    def test_previous_rpu_state_rejected(self):
        self.rpu["header"]["use_prev_vdr_rpu_flag"] = True
        with self.assertRaisesRegex(ValueError, "previous-RPU"):
            normalize(self.rpu, self.identity)

    def test_unsupported_modes_rejected(self):
        for key, value in (("coefficient_data_type", 1), ("rpu_format", 0),
                           ("ext_mapping_idc_0_4", 1), ("coefficient_log2_denom_length", 22)):
            bad = copy.deepcopy(self.rpu)
            bad["header"][key] = value
            with self.assertRaises(ValueError):
                normalize(bad, self.identity)

    def test_malformed_coefficient_arrays_rejected(self):
        self.rpu["rpu_data_mapping"]["curves"][0]["poly_coef"][0] = [0]
        with self.assertRaisesRegex(ValueError, "expected 2 values"):
            normalize(self.rpu, self.identity)

    def test_unknown_nlq_pivots_rejected(self):
        self.rpu["rpu_data_mapping"]["nlq_pred_pivot_value"] = [1, 1022]
        with self.assertRaisesRegex(ValueError, "NLQ pivot range"):
            normalize(self.rpu, self.identity)

    def test_no_mutation_of_original_instructions(self):
        original = copy.deepcopy(self.rpu)
        normalize(self.rpu, self.identity)
        self.assertEqual(self.rpu, original)


if __name__ == "__main__":
    unittest.main()
