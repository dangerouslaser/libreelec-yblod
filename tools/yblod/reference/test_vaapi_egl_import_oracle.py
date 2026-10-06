"""Independent public 4x4 P010 upload oracle; no GPU or driver access."""
import unittest


def public_p010_words():
    y = tuple((64 + 47 * x + 83 * row) << 6
              for row in range(4) for x in range(4))
    cb = tuple((191 + 94 * x + 83 * row) << 6
               for row in range(2) for x in range(2))
    cr = tuple((238 + 94 * x + 83 * row) << 6
               for row in range(2) for x in range(2))
    return y, cb, cr


class P010ImportOracle(unittest.TestCase):
    def test_all_native_codes_against_explicit_independent_anchors(self):
        y, cb, cr = public_p010_words()
        self.assertEqual(tuple(word >> 6 for word in y),
                         (64, 111, 158, 205, 147, 194, 241, 288,
                          230, 277, 324, 371, 313, 360, 407, 454))
        self.assertEqual(tuple(word >> 6 for word in cb), (191, 285, 274, 368))
        self.assertEqual(tuple(word >> 6 for word in cr), (238, 332, 321, 415))

    def test_geometry_and_interleaved_uv_channel_order(self):
        y, cb, cr = public_p010_words()
        self.assertEqual((len(y), len(cb), len(cr)), (16, 4, 4))
        uv = tuple(word for pair in zip(cb, cr) for word in pair)
        self.assertEqual(tuple(word >> 6 for word in uv),
                         (191, 238, 285, 332, 274, 321, 368, 415))
        self.assertEqual(uv[::2], cb)
        self.assertEqual(uv[1::2], cr)
        self.assertEqual(sum(map(len, (y, cb, cr))), 24)

    def test_stored_words_preserve_units_and_low_bits(self):
        for component in public_p010_words():
            for word in component:
                self.assertEqual(word & 63, 0)
                self.assertGreaterEqual(word, 0)
                self.assertLessEqual(word, 65535)
                self.assertEqual(int.from_bytes(word.to_bytes(2, "little"), "little"), word)
        self.assertEqual(public_p010_words()[0][0], 4096)
        self.assertEqual(public_p010_words()[0][-1], 29056)
        self.assertEqual(public_p010_words()[1][-1], 23552)
        self.assertEqual(public_p010_words()[2][-1], 26560)


if __name__ == "__main__":
    unittest.main()
