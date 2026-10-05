import tempfile
from pathlib import Path
import unittest

from extract_frame import (annexb_file, annexb_nals, choose_packet, copy_window, decoded_picture_index,
                           frame_vcl, layer_associations, last_random_access, length_prefixed_nals,
                           packet_vcl_matches, picture_nal_types, random_access_plan,
                           parameter_set_discard_evidence,
                           rpu_presentation_order, split_planes, unhex_dump,
                           verify_picture_geometry, verify_picture_window, write_picture_window)
import hashlib
import copy


def nal(kind, body=b"\x80"):
    return bytes((kind << 1, 1)) + body


class ExtractionTest(unittest.TestCase):
    def test_picture_classification_checks_every_slice(self):
        self.assertEqual(picture_nal_types([nal(32), nal(21), nal(21, b"\x00"), nal(8), nal(8, b"\x00")]), [21, 8])
        for units in ([nal(8, b"\x00")], [nal(8), nal(9, b"\x00")],
                      [nal(8), bytes((16, 2, 0))], [bytes((16, 0, 128))],
                      [bytes((16, 9, 128))], [nal(32)]):
            with self.assertRaises(ValueError):
                picture_nal_types(units)

    def test_cra_plan_discards_only_initial_rasl_and_retains_radl(self):
        types = [21, 8, 9, 6, 7, 1, 21, 8, 9, 1]
        plan = random_access_plan(types, 5, 32)
        self.assertEqual((plan["start"], plan["discarded"]), (0, [1, 2]))
        # A RASL target belonging to the second CRA needs the earlier CRA.
        plan = random_access_plan(types, 8, 32)
        self.assertEqual((plan["start"], plan["discarded"]), (0, [1, 2]))
        self.assertNotIn(8, plan["discarded"])
        self.assertEqual(random_access_plan(types, 9, 32)["start"], 6)
        self.assertEqual(random_access_plan(types, 3, 32)["start"], 0)
        for target, maximum in ((1, 32), (2, 32), (8, 8)):
            with self.assertRaises(ValueError):
                random_access_plan(types, target, maximum)
        with self.assertRaises(ValueError):
            random_access_plan([19, 8, 1], 2, 32)

    def make_picture_packets(self, types):
        packets, encoded = [], []
        offset = 0
        for i, kind in enumerate(types):
            units = [nal(35)]
            if kind in (19, 20, 21):
                units += [nal(32), nal(33), nal(34)]
            units += [nal(kind, b"\x80" + bytes((i + 1,))), nal(kind, b"\x00" + bytes((i + 1,)))]
            data = b"".join(b"\0\0\0\1" + unit for unit in units)
            packets.append({"pos": str(offset), "size": str(len(data))})
            encoded.append(data)
            offset += len(data)
        return packets, encoded

    def test_filtered_window_exact_bytes_offsets_and_reconstruction(self):
        types = [21, 8, 9, 6, 7, 1, 21, 8, 9, 1]
        packets, encoded = self.make_picture_packets(types)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, window = root / "layer.hevc", root / "window.hevc"
            source.write_bytes(b"".join(encoded))
            plan = random_access_plan(types, 8, 32)
            mapping = write_picture_window(source, window, packets, types, plan, range(100, 110))
            retained = [i for i in range(9) if i not in (1, 2)]
            self.assertEqual(window.read_bytes(), b"".join(encoded[i] for i in retained))
            self.assertEqual(mapping["discarded_source_packet_indices"], [101, 102])
            self.assertEqual(mapping["target_window_byte"], sum(len(encoded[i]) for i in retained[:-1]))
            self.assertTrue(verify_picture_window(source, window, mapping))
            for key, value in (("target_window_byte", 0), ("size", 1), ("discarded_source_packet_indices", [])):
                changed = copy.deepcopy(mapping)
                changed[key] = value
                with self.assertRaises(ValueError):
                    verify_picture_window(source, window, changed)
            window.write_bytes(window.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                verify_picture_window(source, window, mapping)

    def test_filtered_window_rejects_mixed_packet_and_stateful_discard(self):
        types = [21, 8, 1]
        for replacement in ([nal(8), nal(9, b"\0")], [nal(32, b"\x81"), nal(8), nal(8, b"\0")],
                            [nal(36), nal(8)], [nal(37), nal(8)]):
            packets, encoded = self.make_picture_packets(types)
            encoded[1] = b"".join(b"\0\0\0\1" + unit for unit in replacement)
            offset = 0
            for packet, data in zip(packets, encoded):
                packet.update(pos=str(offset), size=str(len(data)))
                offset += len(data)
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source.hevc"
                source.write_bytes(b"".join(encoded))
                with self.assertRaises(ValueError):
                    write_picture_window(source, root / "window.hevc", packets, types,
                                         random_access_plan(types, 2, 32), range(3))

    def test_repeated_parameter_sets_allowed_only_when_latest_retained_exact(self):
        state = {}
        self.assertEqual(parameter_set_discard_evidence([nal(34)], True, state, 10), [])
        evidence = parameter_set_discard_evidence([nal(34)], False, state, 11)
        self.assertEqual(evidence, [{"nal_type": 34, "sha256": hashlib.sha256(nal(34)).hexdigest(),
                                    "identical_to_retained_source_packet_index": 10}])
        for units in ([nal(32)], [nal(34, b"\x81")], [nal(36)], [nal(37)]):
            with self.assertRaises(ValueError):
                parameter_set_discard_evidence(units, False, state, 11)
        parameter_set_discard_evidence([nal(34, b"\x81")], True, state, 12)
        # A previously seen definition is not necessarily still current.
        with self.assertRaises(ValueError):
            parameter_set_discard_evidence([nal(34)], False, state, 13)

    def test_identical_parameter_discard_evidence_is_reverified(self):
        types = [21, 8, 1]
        packets, encoded = self.make_picture_packets(types)
        encoded[1] = b"\0\0\0\1" + nal(34) + encoded[1]
        offset = 0
        for packet, data in zip(packets, encoded):
            packet.update(pos=str(offset), size=str(len(data)))
            offset += len(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, window = root / "source.hevc", root / "window.hevc"
            source.write_bytes(b"".join(encoded))
            mapping = write_picture_window(source, window, packets, types, random_access_plan(types, 2, 32), range(3))
            self.assertEqual(len(mapping["packets"][1]["discarded_redundant_parameter_sets"]), 1)
            self.assertTrue(verify_picture_window(source, window, mapping))
            mapping["packets"][1]["discarded_redundant_parameter_sets"] = []
            with self.assertRaises(ValueError):
                verify_picture_window(source, window, mapping)

    def test_streamed_nals_match_at_every_chunk_boundary(self):
        units = [nal(32, b"x" * 31), nal(19, b"\x80\x00\x00\x03\x01"),
                 nal(63, nal(19)), nal(62, b"z" * 57), nal(1, b"\x80\x00")]
        raw = b"\x00" + b"".join((b"\x00\x00\x01" if i % 2 else b"\x00\x00\x00\x01") + n
                                 for i, n in enumerate(units))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stream.hevc"
            path.write_bytes(raw)
            expected = annexb_nals(raw)
            for size in range(4, len(raw) + 2):
                self.assertEqual(list(annexb_file(path, size)), expected, size)

    def test_streamed_nals_reject_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stream.hevc"
            for raw in (b"", b"\0\0", b"garbage\0\0\1abc", b"\0\0\1x", b"\0\0\1\0\0\1xx"):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    list(annexb_file(path, 4))

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
        hashed = layer_associations(iter(units), hash_rpus=True)
        self.assertEqual(hashed[:3], (count, enhancements, instructions))
        self.assertEqual(hashed[3], [hashlib.sha256(r).digest() for r in rpus])

    def test_invalid_layer_associations_rejected(self):
        for units in ([nal(62)], [nal(1), nal(62), nal(62)], [nal(1), nal(63, b"")]):
            with self.assertRaises(ValueError):
                layer_associations(units)

    def test_packet_selection_by_pts_not_counter(self):
        self.assertEqual(choose_packet([{"pts": 10, "dts": 10}, {"pts": 52, "dts": 52}], 52), 1)
        self.assertEqual(choose_packet([{"pts": 1, "dts": 0}], 1), 0)
        for packets in ([{"pts": 1, "dts": 1}, {"pts": 1, "dts": 2}],
                        [{"pts": 1, "dts": 2}, {"pts": 0, "dts": 1}],
                        [{"dts": 1}], [{"pts": 1}], [{"pts": "1", "dts": 1}],
                        [{"pts": 1, "dts": 1}, {"pts": 2}],
                        [{"pts": 1, "dts": 1}, {"pts": 2, "dts": 1}]):
            with self.assertRaises(ValueError):
                choose_packet(packets, 1)

    def test_reordered_packet_selection_uses_coded_order(self):
        packets = [{"pts": 0}, {"pts": 120, "dts": 0}, {"pts": 40, "dts": 40},
                   {"pts": 80, "dts": 80}]
        self.assertEqual(choose_packet(packets, 40), 2)
        self.assertEqual(choose_packet(packets, 120), 1)
        self.assertEqual(rpu_presentation_order(packets, [0, 1, 2, 3], [0, 1, 2, 3], True), [0, 2, 3, 1])
        for rpus, enhancements in (([0, 1, 3], [0, 1, 2, 3]), ([0, 1, 2, 3], [0, 2, 3])):
            with self.assertRaisesRegex(ValueError, "exactly one EL and RPU"):
                rpu_presentation_order(packets, rpus, enhancements, True)
        with self.assertRaisesRegex(ValueError, "exactly one packet"):
            choose_packet(packets, 41)

    def test_nonreordered_missing_layer_compatibility(self):
        packets = [{"pts": i * 40, "dts": i * 40} for i in range(4)]
        self.assertEqual(rpu_presentation_order(packets, [0, 1, 3], [0, 1, 3], False), [0, 1, 2])

    def test_decoded_position_not_coded_ordinal(self):
        decoded = [{"pkt_pos": "0"}, {"pkt_pos": "200"}, {"pkt_pos": "300"}, {"pkt_pos": "100"}]
        self.assertEqual(decoded_picture_index(decoded, 100), 3)
        self.assertEqual(decoded_picture_index(decoded, "200"), 1)
        for frames in ([{"pkt_pos": "100"}, {"pkt_pos": "100"}], [{"pkt_pos": "99"}], [{}]):
            with self.assertRaises(ValueError):
                decoded_picture_index(frames, 100)

    def test_target_geometry_must_not_silently_use_initial_stream_values(self):
        expected = {"width": 3840, "height": 2160, "pix_fmt": "yuv420p10le", "chroma_location": "topleft"}
        self.assertTrue(verify_picture_geometry(expected, dict(expected, pkt_pos="100")))
        for field, value in (("width", 1920), ("height", 1080), ("pix_fmt", "yuv420p"),
                             ("chroma_location", "left"), ("chroma_location", None)):
            changed = dict(expected)
            changed[field] = value
            with self.assertRaises(ValueError):
                verify_picture_geometry(expected, changed)

    def test_decode_window_streams_exact_interval_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "window"
            raw = bytes(range(256)) * 10000
            source.write_bytes(raw)
            copy_window(source, target, 71, len(raw) - 39)
            self.assertEqual(target.read_bytes(), raw[71:-39])
            with self.assertRaises(FileExistsError):
                copy_window(source, target, 71, len(raw) - 39)
            for start, end in ((-1, 3), (2, 2), (3, 2), (0, len(raw) + 1)):
                with self.assertRaises(ValueError):
                    copy_window(source, root / "invalid", start, end)

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
