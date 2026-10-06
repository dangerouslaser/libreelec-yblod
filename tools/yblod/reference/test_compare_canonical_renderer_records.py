import copy
import json
import unittest
import compare_canonical_renderer_records as m

BINARY = 'a' * 64
CODE = [x * 64 for x in '1234']


def record(enabled):
    frames = []
    for i, pts in enumerate(m.PTS):
        frames.append(dict(schema='yblod.canonical-tunnel-fingerprint.v1', pts=pts, el_pts=pts,
            crc_and_repetitions_valid=True, orientation_unambiguous=True,
            capture_stat_identity_unchanged=True, source_metadata_sha256='b'*64,
            canonical_rgb_sha256='c'*64, canonical_packets_sha256='d'*64, packet_count=2,
            route=dict(native=1, native_planar=1, direct_packed=1, batched_planes=0,
                immutable_instructions=0, el_decoder_qsv=enabled, el_qsv_native_used=enabled,
                el_qsv_map_sequence=(i+1)*240 if enabled else 0)))
    return dict(pass_=True, expected_binary_sha256=BINARY, expected_el_qsv=enabled,
        code_closure_verified=True, capture_binary_and_frame_association_verified=True,
        code_sha256=CODE, frames=frames,
        resources=dict(memory_limit_bytes=536870912, swap_limit_bytes=0, swap_current_bytes=0,
            swap_peak_bytes=0, peak_memory_bytes=25000000, cpu_limit=1,
            memory_events=dict(low=0, high=0, max=0, oom=0, oom_kill=0)))


def pair():
    result = [record(0), record(1)]
    for x in result:
        x['pass'] = x.pop('pass_')
    return result


class Tests(unittest.TestCase):
    def test_success_has_no_content_fingerprints_or_numeric_claim(self):
        result = m.compare(*pair(), BINARY, CODE)
        self.assertTrue(result['passed'])
        self.assertFalse(result['literal_pairwise_byte_comparison'])
        rendered = json.dumps(result)
        for private in ('b'*64, 'c'*64, 'd'*64, 'maximum_absolute'):
            self.assertNotIn(private, rendered)

    def test_bad_top_level(self):
        for key, value in (('pass', False), ('expected_binary_sha256', 'e'*64),
                ('expected_el_qsv', True), ('code_closure_verified', False),
                ('capture_binary_and_frame_association_verified', False), ('code_sha256', CODE[:3])):
            a, b = pair(); b[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)

    def test_every_frame_hash_and_timestamp(self):
        for index in range(3):
            for key, value in (('pts', 7), ('el_pts', True), ('source_metadata_sha256', 'e'*64),
                    ('canonical_rgb_sha256', 'e'*64), ('canonical_packets_sha256', 'e'*64),
                    ('packet_count', 3), ('crc_and_repetitions_valid', False),
                    ('orientation_unambiguous', False), ('capture_stat_identity_unchanged', False)):
                a,b=pair();b['frames'][index][key]=value
                with self.subTest(index=index,key=key), self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)

    def test_route_and_mapping(self):
        for key in pair()[1]['frames'][0]['route']:
            a,b=pair();b['frames'][0]['route'][key]=-1
            with self.subTest(key=key), self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)
        a,b=pair();b['frames'][1]['route']['el_qsv_map_sequence']=240
        with self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)

    def test_resource_failure(self):
        for key,value in (('memory_limit_bytes', 2**30), ('swap_limit_bytes', 1),
                ('swap_current_bytes', 1), ('swap_peak_bytes', 1), ('peak_memory_bytes', 0),
                ('cpu_limit', float('nan')), ('memory_events', {})):
            a,b=pair();b['resources'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)
        a,b=pair();b['resources']['memory_events']['oom']=1
        with self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)

    def test_missing_reordered_frames_and_unpinned_code(self):
        a,b=pair();b['frames'].reverse()
        with self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)
        a,b=pair();b['frames'].pop()
        with self.assertRaises(ValueError):m.compare(a,b,BINARY,CODE)
        with self.assertRaises(ValueError):m.compare(*pair(),BINARY,['1'*64]*4)


if __name__ == '__main__':unittest.main()
