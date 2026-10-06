import tempfile
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import canonical_renderer_digest as module
from test_compare_renderer_frames import transport_frame


class Tests(unittest.TestCase):
    def fingerprint(self, frame, pts=1210000000, metadata=b'fixture'):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            info=dict(pts=pts,el_pts=1210000000,width=3840,height=8,
                format='RGBA8 DV tunnel bottom up',native=1,direct_packed=1)
            (folder/'frame.json').write_text(json.dumps(info))
            (folder/'metadata.bin').write_bytes(metadata)
            (folder/'output.rgba').write_bytes(frame.tobytes())
            with patch.object(module.comparator,'H',8):
                return module.canonical_digest(folder)

    def test_all_packet_counts_match_existing_semantic_gate(self):
        for size in (80,200,360,482):
            a=transport_frame(size=size);original=self.fingerprint(a)
            for update_id in range(16):
                b=transport_frame(update_id=update_id,size=size)
                with patch.object(module.comparator,'H',8):
                    self.assertTrue(module.comparator.verify_picture_and_payload(a,b)['picture_and_payload_preserved'])
                for key in ('canonical_rgb_sha256','canonical_packets_sha256'):
                    self.assertEqual(original[key],self.fingerprint(b)[key])

    def test_flipped_orientation(self):
        a=transport_frame()
        self.assertEqual(self.fingerprint(a)['canonical_rgb_sha256'],self.fingerprint(a[::-1])['canonical_rgb_sha256'])

    def test_payload_or_picture_not_equal(self):
        old=self.fingerprint(transport_frame())
        changes=[transport_frame(changed_payload=True)]
        for row,col,channel,bit in ((4,0,0,1),(4,0,1,1),(4,0,2,1),(0,3500,0,1),(0,3500,1,1),(0,3500,2,1),(3,3839,2,16)):
            changed=transport_frame();changed[row,col,channel]^=bit;changes.append(changed)
        for changed in changes:
            try:result=self.fingerprint(changed)
            except ValueError:continue
            self.assertNotEqual(old['canonical_rgb_sha256'],result['canonical_rgb_sha256'])

    def test_invalid_crc_rejected(self):
        bad=transport_frame();bad[0,0,2]^=16
        with self.assertRaises(ValueError):self.fingerprint(bad)

    def test_invalid_repetition_rejected(self):
        bad=transport_frame();other=transport_frame(update_id=7)
        bad.reshape(-1,4)[1024:2048]=other.reshape(-1,4)[1024:2048]
        with self.assertRaises(ValueError):self.fingerprint(bad)

    def test_pts_and_metadata_remain_distinct_keys(self):
        a=self.fingerprint(transport_frame());b=self.fingerprint(transport_frame(),pts=1210000001,metadata=b'other')
        self.assertNotEqual(a['pts'],b['pts']);self.assertNotEqual(a['source_metadata_sha256'],b['source_metadata_sha256'])
        for pts in (True,1210000000.0):
            with self.assertRaises(ValueError):self.fingerprint(transport_frame(),pts=pts)

    def test_source_changed_race(self):
        original=module.comparator.digest
        def mutate(path):
            result=original(path);path.write_bytes(b'changed');return result
        with patch.object(module.comparator,'digest',side_effect=mutate):
            with self.assertRaises(ValueError):self.fingerprint(transport_frame())

    def test_symlink_member_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for name in ('frame.json','metadata.bin','output.rgba'):(folder/name).write_bytes(b'x')
            (folder/'metadata.bin').unlink();(folder/'metadata.bin').symlink_to(folder/'frame.json')
            with self.assertRaises(ValueError):module.canonical_digest(folder)

    def test_alpha_excluded(self):
        a=transport_frame();b=a.copy();b[:,:,3]=255
        self.assertEqual(self.fingerprint(a)['canonical_rgb_sha256'],self.fingerprint(b)['canonical_rgb_sha256'])

if __name__=='__main__':unittest.main()
