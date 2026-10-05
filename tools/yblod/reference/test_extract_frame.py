import tempfile
from pathlib import Path
import unittest

from extract_frame import (annexb_nals, choose_packet, frame_vcl, layer_associations,
                           last_random_access, length_prefixed_nals, packet_vcl_matches, split_planes, unhex_dump)


def nal(kind, body=b"\x80"):
    return bytes((kind << 1, 1)) + body


class ExtractionTest(unittest.TestCase):
    def test_hex_dump_ignores_ascii_column(self):
        self.assertEqual(unhex_dump("\n00000000: 0000 0003 0201 80  .......\n"), b"\0\0\0\3\2\1\x80")

    def test_length_prefixed_nals(self):
        units = [nal(1), nal(62)]
        raw = b"".join(len(n).to_bytes(4, "big") + n for n in units)
        self.assertEqual(length_prefixed_nals(raw, 4), units)
        for bad in (raw[:-1], raw + b"\0", b"\0\0\0\1\0"):
            with self.assertRaises(ValueError):
                length_prefixed_nals(bad, 4)

    def test_annexb_mixed_start_codes(self):
        units = [nal(1), nal(62)]
        self.assertEqual(annexb_nals(b"\0\0\1" + units[0] + b"\0\0\0\1" + units[1]), units)
        with self.assertRaises(ValueError):
            annexb_nals(b"not-hevc")

    def test_multiple_slices_one_frame(self):
        first, rest, second = nal(1), nal(1, b"\x40"), nal(1, b"\x81")
        self.assertEqual(frame_vcl([nal(35), first, rest, nal(35), second], 0), ([first, rest], 2))

    def test_packet_boundary_zero_is_not_frame_content(self):
        self.assertTrue(packet_vcl_matches([nal(1) + b"\0"], [nal(1)]))
        self.assertFalse(packet_vcl_matches([nal(1) + b"\1"], [nal(1)]))
        self.assertFalse(packet_vcl_matches([nal(1), nal(1)], [nal(1)]))

    def test_layer_access_points_are_independent(self):
        self.assertEqual(last_random_access([nal(19), nal(1), nal(21), nal(1)], 3), 2)
        self.assertEqual(last_random_access([nal(19), nal(1), nal(21), nal(1)], 3, (19, 20)), 0)
        self.assertEqual(last_random_access([nal(19), nal(1), nal(1), nal(1)], 3), 0)
        with self.assertRaises(ValueError):
            last_random_access([nal(1)], 0)

    def test_associations_account_for_missing_layers(self):
        units = [nal(1), nal(63, nal(1)), nal(62), nal(1), nal(1), nal(63, nal(1)), nal(62)]
        count, enhancements, instructions, rpus = layer_associations(units)
        self.assertEqual((count, enhancements, instructions), (3, [0, 2], [0, 2]))
        self.assertEqual(rpus, [b"\x80", b"\x80"])

    def test_invalid_layer_associations_rejected(self):
        for units in ([nal(62)], [nal(1), nal(62), nal(62)], [nal(1), nal(63, b"")]):
            with self.assertRaises(ValueError):
                layer_associations(units)

    def test_packet_selection_by_pts_not_counter(self):
        self.assertEqual(choose_packet([{"pts": 10, "dts": 10}, {"pts": 52, "dts": 52}], 52), 1)
        for packets in ([{"pts": 1, "dts": 0}], [{"pts": 1, "dts": 1}, {"pts": 1, "dts": 1}]):
            with self.assertRaises(ValueError):
                choose_packet(packets, 1)

    def test_plane_sizes_and_right_alignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "raw.yuv"
            path.write_bytes(b"\x00\x02" * 6)
            planes = split_planes(path, 2, 2, root, "bl")
            self.assertEqual(planes["Y"]["samples"], 4)
            self.assertEqual(planes["Cb"]["maximum"], 512)
            path.write_bytes(b"\xff\xff" * 6)
            with self.assertRaises(ValueError):
                split_planes(path, 2, 2, root, "bad")


if __name__ == "__main__":
    unittest.main()
