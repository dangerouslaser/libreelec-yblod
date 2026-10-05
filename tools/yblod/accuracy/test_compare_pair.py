#!/usr/bin/env python3
import unittest

import numpy as np

from compare_pair import metadata_packets, stats
from dvtunnel import crc32_mpeg2


class ComparePairTest(unittest.TestCase):
    def test_signed_difference_and_thresholds(self):
        result = stats(np.array([0, 100, 100, 4095], dtype=np.uint16),
                       np.array([0, 101, 96, 4078], dtype=np.uint16))
        self.assertEqual(result["mean_signed_codes"], -5)
        self.assertEqual(result["max_absolute_codes"], 17)
        self.assertEqual(result["identical_percent"], 25)
        self.assertEqual(result["within_1_code_percent"], 50)
        self.assertEqual(result["within_4_codes_percent"], 75)
        self.assertEqual(result["over_16_codes_percent"], 25)

    def test_all_metadata_packets_and_parity(self):
        payload = bytes(range(124))
        packet = payload + crc32_mpeg2(payload).to_bytes(4, "big")
        bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
        y = np.arange(6144, dtype=np.int32) % 4096
        c = (y * 3 % 4096) & ~1
        for start in (0, 3072):
            for i, bit in enumerate(bits):
                p = (int(y[start + i]).bit_count() + int(c[start + i] >> 1).bit_count()) & 1
                c[start + i] |= int(bit) ^ p
        self.assertEqual(metadata_packets(y, c, 2), [packet, packet])
        c[3072 + 20] ^= 1
        with self.assertRaisesRegex(ValueError, "packet 1 failed CRC"):
            metadata_packets(y, c, 2)


if __name__ == "__main__":
    unittest.main()
