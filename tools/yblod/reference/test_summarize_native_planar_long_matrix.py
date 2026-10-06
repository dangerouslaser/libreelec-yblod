import json
from pathlib import Path
import tempfile
import unittest

from summarize_native_planar_long_matrix import aggregate
from test_summarize_native_planar_matrix import write_planar_matrix


def write_long_matrix(root, movie_id=3391):
    write_planar_matrix(root)
    title = {3391: 'Saving Private Ryan', 51: '1917'}[movie_id]
    for order, flag in enumerate((0, 1, 1, 0), 1):
        old = f'native-planar-{order}-flag{flag}'
        new = f'native-planar-long-movie{movie_id}-{order}-flag{flag}'
        for path in list(root.glob(old+'.*')):
            path.rename(root/(new+path.name[len(old):]))
        path = root/(new+'.json')
        raw = json.loads(path.read_text())
        raw.update(label=new, movie_id=movie_id, media=title,
                   requested_seconds=600, elapsed_seconds=600)
        raw['subtitle_fixture']['movie_id'] = movie_id
        raw['selected_log_lines'] = [line.replace('pts_s=1370', 'pts_s=1790')
                                     for line in raw['selected_log_lines']]
        duration = (580, 590, 598, 585)[order-1]
        raw['gpu_samples'][-1]['monotonic_ns'] = int((duration+1)*1e9)
        for interval in raw['gpu_intervals']:
            interval['elapsed_seconds'] = duration/2
        path.write_text(json.dumps(raw))


class Tests(unittest.TestCase):
    def test_both_titles_duration_weighting_routes_subtitles_and_privacy(self):
        for movie, title in ((3391, 'Saving Private Ryan'), (51, '1917')):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root, movie)
                result = aggregate(root, '0'*64, movie, title)
                self.assertEqual(result['seconds_per_case'], 600)
                self.assertAlmostEqual(result['before']['gpu_engine_busy_percent']['render'],
                                       (580*70+585*50)/1165)
                self.assertAlmostEqual(result['after']['gpu_engine_busy_percent']['render'],
                                       (590*60+598*30)/1188)
                self.assertAlmostEqual(result['before']['whole_kodi_cpu_percent_one_core'], 100*.4/1165)
                self.assertEqual(result['subtitle_fixture']['original_preferences_restored_cases'], 4)
                self.assertEqual(result['lifecycle']['dv_display_restoration_failure_cases'], 4)
                self.assertFalse(result['lifecycle']['successful_dv_display_restoration_claimed'])
                for condition, planar in (('before', 0), ('after', 100)):
                    routes = result[condition]['renderer_preparation_routes']
                    self.assertEqual(routes['direct_preparation_percent'], 100)
                    self.assertEqual(routes['native_planar_preparation_percent'], planar)
                self.assertNotIn('do-not-publish', json.dumps(result, allow_nan=False))

    def test_wrong_title_scene_hash_and_short_elapsed_refused(self):
        edits = (lambda r: r.update(label='wrong'), lambda r: r.update(media='1917'),
                 lambda r: r.update(movie_id=51), lambda r: r.update(seek_seconds=0),
                 lambda r: r.update(requested_seconds=180), lambda r: r.update(elapsed_seconds=599),
                 lambda r: r['runtime_after'].update(binary_sha256='1'*64))
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                path = root/'native-planar-long-movie3391-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 3391, 'Saving Private Ryan')

    def test_cpu_gpu_source_windows_below570_refused(self):
        edits = (
            lambda r: r['gpu_samples'][-1].update(monotonic_ns=570_000_000_000),
            lambda r: r.update(gpu_intervals=[dict(elapsed_seconds=284, engine_busy_percent=dict(render=1))]*2),
            lambda r: r.update(selected_log_lines=[line.replace('pts_s=1790', 'pts_s=1370')
                                                    for line in r['selected_log_lines']]))
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                path = root/'native-planar-long-movie3391-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 3391, 'Saving Private Ryan')

    def test_mixed_route_bad_planar_and_subtitle_restoration_refused(self):
        edits = (
            lambda r: r.update(selected_log_lines=[line.replace('direct=460 composed=20', 'direct=400 composed=80')
                                                    for line in r['selected_log_lines']]),
            lambda r: r.update(selected_log_lines=[line.replace('native_planar=480', 'native_planar=479')
                                                    for line in r['selected_log_lines']]),
            lambda r: r['subtitle_fixture']['disabled_at_end'].update(enabled=True),
            lambda r: r['subtitle_fixture']['restored'].update(enabled=False),
            lambda r: r['subtitle_fixture']['disabled'].update(index=False))
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                path = root/'native-planar-long-movie3391-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 3391, 'Saving Private Ryan')

    def test_capture_fallback_bad_shutdown_and_incomplete_matrix_refused(self):
        for suffix, value in (('.kodi.log', 'DVBridge output capture: success=true'),
                              ('.kodi.log', 'DVBridge native reconstruction: fallback=release'),
                              ('.shutdown.json', '{}'), ('.journal.log', 'SIGKILL')):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_long_matrix(root)
                (root/('native-planar-long-movie3391-2-flag1'+suffix)).write_text(value)
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 3391, 'Saving Private Ryan')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            (root/'native-planar-long-movie3391-4-flag0.json').unlink()
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64, 3391, 'Saving Private Ryan')

    def test_valid_but_different_original_subtitle_state_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            path = root/'native-planar-long-movie3391-3-flag1.json'
            raw = json.loads(path.read_text())
            for phase in ('before', 'disabled', 'disabled_at_end', 'restored'):
                raw['subtitle_fixture'][phase]['index'] = 1
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64, 3391, 'Saving Private Ryan')

    def test_exact570_second_windows_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_long_matrix(root)
            for path in root.glob('native-planar-long-movie3391-*-flag?.json'):
                raw = json.loads(path.read_text())
                raw['gpu_samples'][-1]['monotonic_ns'] = 571_000_000_000
                for interval in raw['gpu_intervals']:
                    interval['elapsed_seconds'] = 285
                raw['selected_log_lines'] = [line.replace('pts_s=1790', 'pts_s=1780')
                                             for line in raw['selected_log_lines']]
                path.write_text(json.dumps(raw))
            result = aggregate(root, '0'*64, 3391, 'Saving Private Ryan')
            self.assertEqual(result['before']['gpu_elapsed_seconds'], 1140)


if __name__ == '__main__':
    unittest.main()
