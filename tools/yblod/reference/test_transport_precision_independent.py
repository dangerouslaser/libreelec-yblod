"""Literal/scalar tunnel checks, independent of production packer fixtures.

Local stdlib tests establish exact answers. NumPy tests exercise production
packing/unpacking and precision diagnostics, and must run before release.
"""
import unittest

from transport_oracle import (ce_frame, co_sited_position, decode_ce as scalar_ce,
                              decode_rgb, pixel_rgb, rgb_frame, signed_parts)

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    from compare_output import decode_ce, unpack_rgb
    from output_frame import pack
    from transport_precision import coordinate_masks, finish, new_accumulator, update


PAIRS = ((0xABC, 0x123), (0xDEF, 0x456), (0x001, 0xABC), (0xFFE, 0xDEF),
         (0x123, 0xFFF), (0x456, 0x000), (0x789, 0x246), (0xFED, 0x135))
RGB_LITERAL = bytes.fromhex("12ab3c 45de6f ab00c1 defffe ff12f3 004506 247869 13fe5d")
# Three independently written 64-bit words. Pixel boundaries do not align to
# word boundaries: the first word contains two pixels plus G/B of pixel2.
CE_LITERAL = bytes.fromhex("c100456fde123cab 45fff312defeffab 135dfe2469780006")
SOURCE_ROW = ((0xABC, 0x123, 0x456), (0xDEF, 99, 77),
              (0x001, 0xABC, 0xDEF), (0xFFE, 88, 66),
              (0x123, 0xFFF, 0x000), (0x456, 55, 33),
              (0x789, 0x246, 0x135), (0xFED, 22, 11))


class ScalarTransportTests(unittest.TestCase):
    def test_literal_rgb_bytes_without_roundtrip(self):
        self.assertEqual(pixel_rgb(0xABC, 0x123), bytes((0x12, 0xAB, 0x3C)))
        self.assertEqual(pixel_rgb(0xDEF, 0x456), bytes((0x45, 0xDE, 0x6F)))
        self.assertEqual(rgb_frame([SOURCE_ROW]), RGB_LITERAL)
        self.assertEqual(decode_rgb(RGB_LITERAL), list(PAIRS))

    def test_literal_64bit_memory_words_without_production_packer(self):
        self.assertEqual(CE_LITERAL[:8], bytes((0xC1, 0x00, 0x45, 0x6F, 0xDE, 0x12, 0x3C, 0xAB)))
        self.assertEqual(len(CE_LITERAL), 24)
        self.assertEqual(scalar_ce(CE_LITERAL), list(PAIRS))
        self.assertEqual(ce_frame([SOURCE_ROW]), CE_LITERAL)

    def test_all_codes_and_individual_nibble_values(self):
        for value in range(4096):
            encoded = pixel_rgb(value, 4095-value)
            self.assertEqual(decode_rgb(encoded), [(value, 4095-value)])
        for i_low in range(16):
            for c_low in range(16):
                self.assertEqual(pixel_rgb(0xA00+i_low, 0xB00+c_low), bytes((0xB0, 0xA0, c_low*16+i_low)))

    def test_scalar_field_validation(self):
        for value in (-1, 4096, 0.0, True):
            with self.assertRaises(ValueError):
                pixel_rgb(value, 0)
        with self.assertRaises(ValueError):
            scalar_ce(CE_LITERAL[:8])

    def test_carry_borrow_and_nonadditive_absolute_errors(self):
        for a, b, full, weighted, low in ((16, 15, 1, 16, -15), (15, 16, -1, -16, 15),
                                         (4095, 0, 4095, 4080, 15), (0, 4095, -4095, -4080, -15),
                                         (0xAB0, 0xABC, -12, 0, -12)):
            result = signed_parts(a, b)
            self.assertEqual((result["delta12"], result["weighted_high8"], result["delta_low4"]), (full, weighted, low))
            self.assertEqual(full, weighted+low)
        carry = signed_parts(16, 15)
        self.assertNotEqual(abs(carry["delta12"]), abs(carry["weighted_high8"])+abs(carry["delta_low4"]))

    def test_every_neighboring_code_transition_and_reverse(self):
        for value in range(1, 4096):
            for a, b in ((value, value-1), (value-1, value)):
                parts = signed_parts(a, b)
                self.assertEqual(parts["delta12"], parts["weighted_high8"]+parts["delta_low4"])
                self.assertEqual(abs(parts["delta12"]), 1)

    def test_global_coordinates_and_co_sited_chroma(self):
        for row in (1, 31, 32, 275, 276):
            self.assertEqual(co_sited_position(row, 6, "P"), (row, 6))
            self.assertEqual(co_sited_position(row, 7, "T"), (row, 6))
            self.assertEqual(co_sited_position(row, 7, "I"), (row, 7))
        for channel, x in (("P", 7), ("T", 6)):
            with self.assertRaises(ValueError):
                co_sited_position(275, x, channel)


@unittest.skipIf(np is None, "NumPy required for production transport checks")
class ProductionTransportTests(unittest.TestCase):
    def test_fixed_literal_rgb_packer_and_unpacker(self):
        self.assertEqual(pack(np.array([SOURCE_ROW], dtype=np.uint16)).tobytes(), RGB_LITERAL)
        raw = np.frombuffer(RGB_LITERAL, dtype=np.uint8).reshape(1, 8, 3)
        intensity, chroma = unpack_rgb(*np.moveaxis(raw, -1, 0))
        np.testing.assert_array_equal(intensity, [[i for i, _ in PAIRS]])
        np.testing.assert_array_equal(chroma, [[c for _, c in PAIRS]])

    def test_ce_decoder_fixed_literal_words_not_a_packer_roundtrip(self):
        raw = np.frombuffer(CE_LITERAL, dtype=np.uint8).reshape(1, 8, 3)
        intensity, chroma = decode_ce(raw)
        np.testing.assert_array_equal(intensity, [[i for i, _ in PAIRS]])
        np.testing.assert_array_equal(chroma, [[c for _, c in PAIRS]])

    def test_each_wire_bit_has_one_exact_owner(self):
        for byte_index in range(24):
            for bit in range(8):
                raw = bytearray(24)
                raw[byte_index] = 1 << bit
                expected = scalar_ce(raw)
                intensity, chroma = decode_ce(np.frombuffer(raw, dtype=np.uint8).reshape(1, 8, 3))
                np.testing.assert_array_equal(intensity, [[i for i, _ in expected]])
                np.testing.assert_array_equal(chroma, [[c for _, c in expected]])
                self.assertEqual(sum(int(v).bit_count() for pair in expected for v in pair), 1)

    def test_all4096_codes_and_odd_pixel_chroma_ignored(self):
        row = []
        for value in range(4096):
            row.extend((((3*value)%4096, value, 4095-value), ((5*value+1)%4096, 17, 3000)))
        expected_i = [v for value in range(4096) for v in ((3*value)%4096, (5*value+1)%4096)]
        expected_c = [v for value in range(4096) for v in (value, 4095-value)]
        self.assertEqual(pack(np.array([row], dtype=np.uint16)).tobytes(), rgb_frame([row]))
        intensity, chroma = decode_ce(np.frombuffer(ce_frame([row]), dtype=np.uint8).reshape(1, 8192, 3))
        np.testing.assert_array_equal(intensity, [expected_i])
        np.testing.assert_array_equal(chroma, [expected_c])

    def test_row_and_odd_strip_boundaries_keep_word_origin(self):
        rows = [[((y*211+x*17)%4096, (y*31+x*5)%4096, (4095-y*13-x*7)%4096)
                 for x in range(8)] for y in range(35)]
        raw = np.frombuffer(ce_frame(rows), dtype=np.uint8).reshape(35, 8, 3)
        for first, last in ((0, 1), (1, 31), (31, 33), (33, 35)):
            intensity, chroma = decode_ce(raw[first:last])
            expected_i = [[row[x][0] for x in range(8)] for row in rows[first:last]]
            expected_c = [[row[x-x%2][1 if x%2 == 0 else 2] for x in range(8)] for row in rows[first:last]]
            np.testing.assert_array_equal(intensity, expected_i)
            np.testing.assert_array_equal(chroma, expected_c)

    def test_precision_masks_use_global_rows_and_chroma_sample_columns(self):
        rows = np.array([275, 276, 277])
        # Active picture begins at physical x6. P at6 and T stored at7 share
        # chroma sample column3 (odd), not array-local column0 (even).
        for physical_x in (6, 7):
            columns = np.array([physical_x//2, physical_x//2+1])
            masks = coordinate_masks(rows, columns)
            np.testing.assert_array_equal(masks["even_row"], [[False, False], [True, True], [False, False]])
            np.testing.assert_array_equal(masks["odd_row"], [[True, True], [False, False], [True, True]])
            np.testing.assert_array_equal(masks["even_sample_column"], [[False, True]]*3)
            np.testing.assert_array_equal(masks["odd_sample_column"], [[True, False]]*3)
            np.testing.assert_array_equal(masks["row_odd_column_odd"], [[True, False], [False, False], [True, False]])

    def test_precision_carry_decomposition_is_signed_and_not_absolute_additive(self):
        accumulator = new_accumulator()
        update(accumulator, np.array([16], dtype=np.uint16), np.array([15], dtype=np.uint16))
        result = finish(accumulator)
        signed = result["signed_decomposition"]
        self.assertTrue(signed["identity_exact"])
        self.assertEqual((signed["delta12_sum"], signed["weighted_high8_sum"], signed["low4_sum"]), (1, 16, -15))
        self.assertEqual((signed["mean_delta12_codes"], signed["mean_weighted_high8_codes"], signed["mean_low4_codes"]), (1., 16., -15.))
        absolute = result["absolute_errors_not_additive"]
        self.assertEqual(absolute, {"mean_delta12_codes": 1., "mean_weighted_high8_codes": 16., "mean_low4_codes": 15.})
        self.assertEqual(result["events"]["opposite_signed_components"], 1)

    def test_precision_histograms_bits_and_streamed_carry_borrow_fixture(self):
        accumulator = new_accumulator()
        # Split accumulation intentionally at a non-word/non-pair boundary.
        update(accumulator, np.array([16]), np.array([15]))
        update(accumulator, np.array([15, 4095, 0]), np.array([16, 0, 4095]))
        result = finish(accumulator)
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["delta12_histogram_nonzero_bins"], [[-4095, 1], [-1, 1], [1, 1], [4095, 1]])
        signed = result["signed_decomposition"]
        self.assertEqual((signed["delta12_sum"], signed["weighted_high8_sum"], signed["low4_sum"]), (0, 0, 0))
        self.assertEqual(result["absolute_errors_not_additive"],
                         {"mean_delta12_codes": 2048., "mean_weighted_high8_codes": 2048., "mean_low4_codes": 15.})
        for side in ("generated", "capture"):
            values = result["values"][side]
            self.assertEqual(values["code_mod16_histogram"], [2]+[0]*14+[2])
            self.assertEqual(values["code_mod4_histogram"], [2, 0, 0, 2])
            self.assertEqual(values["high8_histogram"], [2, 1]+[0]*253+[1])
            self.assertEqual(values["mean_low4_value"], 7.5)
            self.assertEqual(values["mean_high8_value"], 64.)
        for bit, record in enumerate(result["bit_counts"]):
            with self.subTest(bit=bit):
                self.assertEqual(record["bit"], bit)
                self.assertEqual(record["generated_set"], 2 if bit < 5 else 1)
                self.assertEqual(record["capture_set"], 2 if bit < 5 else 1)
                self.assertEqual(record["xor_count"], 4 if bit < 5 else 2)
                self.assertEqual(record["xor_rate"], 1. if bit < 5 else .5)


if __name__ == "__main__":
    unittest.main()
