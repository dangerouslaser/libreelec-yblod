import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path
import numpy as np
import compare_renderer_frames as module


def packed(y=100, c=200):
    frame = np.zeros((8, 4, 4), dtype=np.uint8)
    frame[:, :, 0] = c >> 4
    frame[:, :, 1] = y >> 4
    frame[:, :, 2] = (y & 15) | ((c & 15) << 4)
    frame[:, :, 3] = 255
    return frame


def transport_frame(update_id=1, size=200, changed_payload=False):
    from dvtunnel import crc32_mpeg2
    frame = np.zeros((8, 3840, 4), dtype=np.uint8)
    count = 1 if size <= 119 else 1 + (size - 119 + 120) // 121
    for index in range(count):
        packet = bytearray(128)
        packet[0] = (0 if count == 1 else 1 if index == 0 else 3 if index + 1 == count else 2) << 6
        packet[1] = update_id * 17
        if index == 0:
            packet[3:5] = size.to_bytes(2, 'big')
            packet[6] = int(changed_payload)
        packet[124:] = crc32_mpeg2(packet[:124]).to_bytes(4, 'big')
        bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
        frame.reshape(-1, 4)[index*3072:(index+1)*3072, 2] = np.tile(bits, 3) << 4
    return frame


class Tests(unittest.TestCase):
    def run_compare(self, old, new, info_change=None, same_metadata=True, require_exact=False):
        info = dict(pts=1200000000, el_pts=1200000000, native=0, direct_packed=1)
        other = dict(info, native=1, direct_packed=0)
        if info_change:
            other.update(info_change)
        with patch.object(module, 'W', 4), patch.object(module, 'H', 8), \
             patch.object(module, 'load_frame', side_effect=[(info, old, False, 2), (other, new, False, 2)]), \
             patch.object(module, 'digest', side_effect=[b'a', b'a' if same_metadata else b'b']):
            return module.compare(Path('/old'), Path('/new'), require_exact)

    def test_identical_outputs(self):
        result = self.run_compare(packed(), packed())
        for plane in result['planes'].values():
            self.assertEqual(plane['max_absolute_codes'], 0)
            self.assertEqual(plane['exact_percent'], 100)
            self.assertIsNone(plane['psnr_db'])
        self.assertTrue(result['output_preserved'])

    def test_known_code_differences(self):
        result = self.run_compare(packed(), packed(y=101, c=204))
        self.assertEqual(result['planes']['I']['mean_absolute_codes'], 1)
        self.assertEqual(result['planes']['I']['over_one_percent'], 0)
        self.assertEqual(result['planes']['P']['mean_absolute_codes'], 4)
        self.assertEqual(result['planes']['T']['at_least_four_percent'], 100)

    def test_metadata_rows_excluded(self):
        new = packed()
        new[:4] = 0
        self.assertEqual(self.run_compare(packed(), new)['planes']['I']['max_absolute_codes'], 0)
        with self.assertRaises(ValueError):
            self.run_compare(packed(), new, require_exact=True)

    def test_exact_gate_and_alpha(self):
        self.run_compare(packed(), packed(), require_exact=True)
        changed = packed()
        changed[:, :, 3] = 0
        self.assertTrue(self.run_compare(packed(), changed, require_exact=True)['output_preserved'])
        with self.assertRaises(ValueError):
            self.run_compare(packed(), packed(y=101), require_exact=True)

    def test_semantic_gate_all_packet_counts(self):
        with patch.object(module, 'H', 8):
            for size in (80, 200, 482):
                result = module.verify_picture_and_payload(transport_frame(size=size),
                    transport_frame(update_id=7, size=size))
                self.assertTrue(result['picture_and_payload_preserved'])

    def test_semantic_gate_rejects_payload_picture_and_repetition_changes(self):
        old = transport_frame()
        with patch.object(module, 'H', 8):
            with self.assertRaises(ValueError):
                module.verify_picture_and_payload(old, transport_frame(changed_payload=True))
            for row, column, bit in ((0, 3500, 1), (4, 0, 1), (0, 0, 16)):
                new = transport_frame(update_id=7)
                new[row, column, 2] ^= bit
                with self.assertRaises(ValueError):
                    module.verify_picture_and_payload(old, new)

    def test_semantic_gate_rejects_crc_valid_malformed_headers(self):
        from dvtunnel import crc32_mpeg2
        with patch.object(module, 'H', 8):
            for index, offset, value in ((0, 1, 0x12), (1, 1, 0x77), (0, 0, 0), (0, 2, 1)):
                frame = transport_frame()
                packet = bytearray(module.decode_packets(frame)[index])
                packet[offset] = value
                packet[124:] = crc32_mpeg2(packet[:124]).to_bytes(4, 'big')
                bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
                frame.reshape(-1, 4)[index*3072:(index+1)*3072, 2] = np.tile(bits, 3) << 4
                with self.assertRaises(ValueError):
                    module.verify_picture_and_payload(transport_frame(), frame)

    def test_real_crc_orientation_and_invalid_capture(self):
        from dvtunnel import crc32_mpeg2
        width, height = 3840, 8
        frame = np.zeros((height, width, 4), dtype=np.uint8)
        payload = bytes(range(124))
        packet = payload + crc32_mpeg2(payload).to_bytes(4, 'big')
        bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
        for packet_index in range(2):
            frame.reshape(-1, 4)[packet_index * 3072:packet_index * 3072 + 1024, 2] = bits << 4
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            info = dict(width=width, height=height, format='RGBA8 DV tunnel bottom up',
                        pts=1200000000, el_pts=1200000000, native=1, direct_packed=0)
            (folder / 'metadata.bin').write_bytes(b'metadata')
            (folder / 'frame.json').write_text(json.dumps(info))
            with patch.object(module, 'W', width), patch.object(module, 'H', height):
                for flip in (False, True):
                    (frame[::-1] if flip else frame).tofile(folder / 'output.rgba')
                    _, _, actual_flip, valid = module.load_frame(folder)
                    self.assertEqual(actual_flip, flip)
                    self.assertEqual(valid, 2)
                frame[:] = 0
                frame.tofile(folder / 'output.rgba')
                with self.assertRaises(ValueError):
                    module.load_frame(folder)
                for invalid in (float('nan'), float('inf'), True, 0):
                    (folder / 'frame.json').write_text(json.dumps(dict(info, pts=invalid)))
                    with self.assertRaises(ValueError):
                        module.load_frame(folder)

    def test_wrong_source_pair_rejected(self):
        for change in (dict(pts=1200000002), dict(el_pts=1200000002)):
            with self.assertRaises(ValueError):
                self.run_compare(packed(), packed(), change)
        with self.assertRaises(ValueError):
            self.run_compare(packed(), packed(), same_metadata=False)


if __name__ == '__main__':
    unittest.main()
