import copy
import unittest
from el_qsv_raw_evidence import translate


def fixture():
    identity = {key: True for key in ('target_host_matches_capture_host',
        'physical_gpu_matches_capture_gpu', 'probe_executable_identity_verified',
        'candidate_runtime_identity_verified', 'private_input_identity_verified',
        'identities_unchanged_before_after', 'resource_limits_verified')}
    pts = [1210000000, 1220000000, 1230000000]
    probe = {key: True for key in ('pass', 'input_stat_identity_unchanged',
        'expected_sdk_libvpl_loaded', 'expected_sdk_implementation_loaded',
        'expected_sdk_va_driver_loaded')}
    probe.update(qsv_mapped_frames=3, frames=[])
    for time in pts:
        frame = {key: True for key in ('properties_equal', 'active_geometry_equal',
            'chroma_location_equal', 'colour_properties_equal', 'original_timestamps_equal')}
        frame.update(requested_pts_microseconds=time, format='P010', code_bit_depth=10,
            active_width=1920, active_height=1080,
            before=dict(pts_microseconds=time), after=dict(pts_microseconds=time),
            planes=[dict(plane=plane, sample_count=count, differing_samples=0,
                maximum_absolute_sample_codes=0, p010_low_bits_zero=True)
                for plane, count in dict(Y=2073600, U=518400, V=518400).items()])
        probe['frames'].append(frame)
    return probe, identity, pts


class Evidence(unittest.TestCase):
    def test_exact_translation(self):
        result = translate(*fixture())
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['planes']['Y']['differing_storage_samples'], 0)

    def test_every_identity_must_be_strict_true(self):
        for key in fixture()[1]:
            for value in (False, 1, None, 'true'):
                probe, identity, pts = fixture()
                identity[key] = value
                with self.assertRaises(ValueError):
                    translate(probe, identity, pts)

    def test_nonzero_or_bool_measurements_fail(self):
        for key in ('sample_count', 'differing_samples', 'maximum_absolute_sample_codes'):
            for value in (True, -1, 1):
                probe, identity, pts = fixture()
                probe['frames'][0]['planes'][0][key] = value
                with self.assertRaises(ValueError):
                    translate(probe, identity, pts)

    def test_wrong_pts_duplicate_planes_and_false_properties_fail(self):
        for kind in ('pts', 'planes', 'props', 'lowbits', 'mapped'):
            probe, identity, pts = fixture()
            if kind == 'pts': probe['frames'][0]['after']['pts_microseconds'] += 1
            if kind == 'planes': probe['frames'][0]['planes'][1]['plane'] = 'Y'
            if kind == 'props': probe['frames'][0]['properties_equal'] = 1
            if kind == 'lowbits': probe['frames'][0]['planes'][0]['p010_low_bits_zero'] = 1
            if kind == 'mapped': probe['qsv_mapped_frames'] = True
            with self.assertRaises(ValueError): translate(probe, identity, pts)


if __name__ == '__main__': unittest.main()
