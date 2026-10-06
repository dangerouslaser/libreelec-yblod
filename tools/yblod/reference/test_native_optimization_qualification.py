import copy
import json
from pathlib import Path
import tempfile
import unittest

from native_optimization_qualification import qualify_frames


def proof(option='batched_planes'):
    frames = []
    for index in range(3):
        frame = dict(source_timestamps_equal=True, source_metadata_equal=True,
                     picture_and_payload_preserved=True,
                     maximum_absolute_12bit_codes=dict(I=0, P=0, T=0),
                     exact_picture_percent=dict(I=100, P=100, T=100))
        for phase, enabled in (('before', 0), ('after', 1)):
            route = dict(native=1, direct_packed=1, native_planar=1, qsv_mode=1,
                         batched_planes=0, immutable_instructions=0)
            route[option] = enabled
            frame[phase] = dict(route=route, pts_microseconds=1210000000+index*10000000,
                               el_pts_microseconds=1210000000+index*10000000)
        frames.append(frame)
    return dict(schema='yblod.native-optimization-frame-results.v1', binary_sha256='0'*64,
                optimization=option, content='Saving Private Ryan', movie_id=3391,
                seek_seconds=1200, frames=frames)


class Tests(unittest.TestCase):
    def evaluate(self, report, option='batched_planes'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'proof.json'
            path.write_text(json.dumps(report))
            return qualify_frames(path, '0'*64, option)

    def test_both_isolated_options_pass(self):
        for option in ('batched_planes', 'immutable_instructions'):
            result = self.evaluate(proof(option), option)
            self.assertTrue(result['native_packed_planar_both'])
            self.assertTrue(result['other_optimization_disabled'])

    def test_wrong_candidate_scene_or_option_rejected(self):
        for key, value in (('binary_sha256', '1'*64), ('movie_id', 51),
                           ('content', '1917'), ('seek_seconds', 1201),
                           ('optimization', 'immutable_instructions')):
            report = proof()
            report[key] = value
            with self.assertRaises(ValueError):
                self.evaluate(report)

    def test_precision_source_and_actual_route_rejected(self):
        edits = (
            lambda f: f.update(source_metadata_equal=False),
            lambda f: f.update(source_timestamps_equal=1),
            lambda f: f.update(picture_and_payload_preserved=False),
            lambda f: f['maximum_absolute_12bit_codes'].update(T=1),
            lambda f: f['exact_picture_percent'].update(I=99.999),
            lambda f: f['after']['route'].update(immutable_instructions=1),
            lambda f: f['after']['route'].update(batched_planes=True),
            lambda f: f['after']['route'].pop('batched_planes'),
            lambda f: f['after']['route'].update(native_planar=0),
            lambda f: f['after'].update(el_pts_microseconds=1210000001),
        )
        for edit in edits:
            report = proof()
            edit(report['frames'][0])
            with self.assertRaises(ValueError):
                self.evaluate(report)

    def test_missing_duplicate_or_unsorted_frames_rejected(self):
        report = proof()
        for frames in (report['frames'][:2], [report['frames'][0]]*3,
                       list(reversed(report['frames']))):
            changed = copy.deepcopy(report)
            changed['frames'] = frames
            with self.assertRaises(ValueError):
                self.evaluate(changed)


if __name__ == '__main__':
    unittest.main()
