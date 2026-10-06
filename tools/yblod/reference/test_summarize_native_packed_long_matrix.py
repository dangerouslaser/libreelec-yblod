import json
from pathlib import Path
import tempfile
import unittest

from summarize_native_packed_long_matrix import aggregate
from test_summarize_native_packed_matrix import write_matrix


def write_long_matrix(root, movie_id=51, seconds=600):
    write_matrix(root)
    title = {51: '1917', 3391: 'Saving Private Ryan'}[movie_id]
    for order, flag in enumerate((0, 1, 1, 0), 1):
        old = f'native-packed-{order}-flag{flag}'
        new = f'native-packed-long-movie{movie_id}-{order}-flag{flag}'
        for path in list(root.glob(old+'.*')):
            path.rename(root/(new+path.name[len(old):]))
        path = root/(new+'.json')
        raw = json.loads(path.read_text())
        raw.update(label=new, media=title, movie_id=movie_id, requested_seconds=seconds,
                   elapsed_seconds=seconds, private_frame_path='/private/unpublished-frame',
                   private_metadata_bytes='not-public')
        raw['selected_log_lines'] = [line.replace('pts_s=1370', f'pts_s={1200+seconds-10}')
                                     for line in raw['selected_log_lines']]
        path.write_text(json.dumps(raw))


class Tests(unittest.TestCase):
    def test_both_titles_pooled_metrics_and_sanitization(self):
        for movie, title in ((51, '1917'), (3391, 'Saving Private Ryan')):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root, movie)
                result = aggregate(root, '0'*64, movie, title)
                self.assertEqual(result['seconds_per_case'], 600)
                self.assertEqual(result['before']['gpu_engine_busy_percent']['render'], 55)
                self.assertEqual(result['after']['gpu_engine_busy_percent']['render'], 40)
                self.assertEqual(result['cases'][0]['raw_health']['maximum_observed_skip_total'], 1)
                self.assertEqual(result['cases'][0]['health']['skip_delta'], 0)
                encoded = json.dumps(result, allow_nan=False)
                self.assertNotIn('unpublished-frame', encoded)
                self.assertNotIn('not-public', encoded)

    def test_bounds_wrong_title_and_candidate_hash_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            for kwargs in (dict(seconds=299), dict(seconds=901), dict(seek_seconds=-1),
                           dict(title='Saving Private Ryan'), dict(movie_id=999),
                           dict(binary_hash='bad'), dict(binary_hash='1'*64)):
                request = dict(root=root, binary_hash='0'*64, movie_id=51, title='1917')
                request.update(kwargs)
                with self.assertRaises(ValueError):
                    aggregate(**request)

    def test_raw_case_metadata_and_insufficient_duration_refused(self):
        edits = (lambda r: r.update(media='Saving Private Ryan'), lambda r: r.update(movie_id=3391),
                 lambda r: r.update(requested_seconds=180), lambda r: r.update(seek_seconds=0),
                 lambda r: r.update(label='wrong'), lambda r: r.update(elapsed_seconds=599),
                 lambda r: r.update(expected_route='integer'),
                 lambda r: r.update(selected_log_lines=[line.replace('pts_s=1790', 'pts_s=1370')
                                                        for line in r['selected_log_lines']]))
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                path = root/'native-packed-long-movie51-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 51, '1917')

    def test_capture_logs_and_incomplete_or_extra_cases_refused(self):
        for marker in ('DVBridge output capture: success=true', 'DVBridge capture pair: success=true'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                (root/'native-packed-long-movie51-2-flag1.kodi.log').write_text(marker)
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 51, '1917')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            path = root/'native-packed-long-movie51-5-flag0.json'
            path.write_text('{}')
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64, 51, '1917')
            path.unlink()
            (root/'native-packed-long-movie51-4-flag0.json').unlink()
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64, 51, '1917')

    def test_explicit_mixed_route_summary_reports_actual_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            for order in (2, 3):
                path = root/f'native-packed-long-movie51-{order}-flag1.json'
                raw = json.loads(path.read_text())
                raw['selected_log_lines'] = [line.replace('direct=460 composed=20', 'direct=400 composed=80')
                                             for line in raw['selected_log_lines']]
                path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64, 51, '1917')
            result = aggregate(root, '0'*64, 51, '1917', allow_mixed=True)
            self.assertTrue(result['mixed_routes_allowed'])
            exposure = result['after']['renderer_preparation_routes']
            self.assertEqual((exposure['direct'], exposure['composed'], exposure['prepared']), (600, 120, 720))
            self.assertAlmostEqual(exposure['direct_percent'], 100*600/720)


if __name__ == '__main__':
    unittest.main()
