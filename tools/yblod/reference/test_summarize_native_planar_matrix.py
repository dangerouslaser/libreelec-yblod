import json
from pathlib import Path
import tempfile
import unittest

from summarize_native_planar_matrix import aggregate
from test_native_planar_matrix import planar_report
from test_summarize_native_packed_matrix import write_matrix


def write_planar_matrix(root):
    write_matrix(root)
    for order, flag in enumerate((0, 1, 1, 0), 1):
        old = f'native-packed-{order}-flag{flag}'
        new = f'native-planar-{order}-flag{flag}'
        for path in list(root.glob(old+'.*')):
            path.rename(root/(new+path.name[len(old):]))
        path = root/(new+'.json')
        raw = json.loads(path.read_text())
        raw.update(label=new, private_frame_path='/private/do-not-publish',
                   private_metadata_bytes='do-not-publish-metadata')
        original = dict(enabled=True, index=0)
        disabled = dict(enabled=False, index=0)
        raw['subtitle_fixture'] = dict(movie_id=3391, player_id=1, requested_enabled=False,
            before=original.copy(), disabled=disabled.copy(), disabled_at_end=disabled.copy(),
            restored=original.copy(), private_note='do-not-publish-subtitle')
        correct, _ = planar_report(flag)
        raw['selected_log_lines'] = [line for line in raw['selected_log_lines']
                                     if 'DVBridge renderer summary:' not in line]
        raw['selected_log_lines'] += [line for line in correct['selected_log_lines']
                                      if 'DVBridge renderer summary:' in line]
        duration = (160, 170, 180, 175)[order-1]
        raw['gpu_samples'][-1]['monotonic_ns'] = int((duration+1)*1e9)
        for interval in raw['gpu_intervals']:
            interval['elapsed_seconds'] = duration/2
        path.write_text(json.dumps(raw))
        (root/(new+'.kodi.log')).write_text(
            'DVBridge: output restoration failed; retaining scanout state; failures=1\n')


class Tests(unittest.TestCase):
    def test_actual_duration_weighting_routes_and_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_planar_matrix(root)
            result = aggregate(root, '0'*64)
            self.assertEqual(result['matrix'], [0, 1, 1, 0])
            self.assertTrue(result['packed_output_enabled_in_both'])
            self.assertEqual(result['subtitle_fixture']['original_state'], dict(enabled=True, index=0))
            self.assertEqual(result['subtitle_fixture']['original_preferences_restored_cases'], 4)
            self.assertAlmostEqual(result['before']['gpu_engine_busy_percent']['render'],
                                   (160*70+175*50)/335)
            self.assertAlmostEqual(result['after']['gpu_engine_busy_percent']['render'],
                                   (170*60+180*30)/350)
            self.assertAlmostEqual(result['before']['whole_kodi_cpu_percent_one_core'], 100*.4/335)
            for condition, expected in (('before', 0), ('after', 100)):
                routes = result[condition]['renderer_preparation_routes']
                self.assertEqual(routes['direct_preparation_percent'], 100)
                self.assertEqual(routes['native_planar_preparation_percent'], expected)
            self.assertEqual(result['lifecycle']['normal_process_exit_cases'], 4)
            self.assertEqual(result['lifecycle']['dv_display_restoration_failure_cases'], 4)
            self.assertFalse(result['lifecycle']['successful_dv_display_restoration_claimed'])
            text = json.dumps(result, allow_nan=False)
            self.assertNotIn('do-not-publish', text)

    def test_metadata_duration_hash_and_route_refused(self):
        edits = (
            lambda r: r.update(label='wrong'), lambda r: r.update(media='1917'),
            lambda r: r.update(movie_id=51), lambda r: r.update(seek_seconds=0),
            lambda r: r.update(requested_seconds=300), lambda r: r.update(elapsed_seconds=179),
            lambda r: r.update(expected_route='integer'),
            lambda r: r['runtime_after'].update(binary_sha256='1'*64),
            lambda r: r.update(selected_log_lines=[line.replace('native_planar=480', 'native_planar=479')
                                                    for line in r['selected_log_lines']]),
            lambda r: r.update(selected_log_lines=[line.replace('direct=460 composed=20', 'direct=400 composed=80')
                                                    for line in r['selected_log_lines']]),
            lambda r: r.update(gpu_intervals=[dict(elapsed_seconds=1, engine_busy_percent=dict(render=1))]*2),
            lambda r: r['gpu_samples'][-1].update(monotonic_ns=2_000_000_000),
        )
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_planar_matrix(root)
                path = root/'native-planar-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_readback_fallback_and_process_failure_refused(self):
        for suffix, content in (
                ('.kodi.log', 'DVBridge output capture: success=true'),
                ('.kodi.log', 'DVBridge capture pair: success=true'),
                ('.kodi.log', 'DVBridge native reconstruction: fallback=release'),
                ('.kodi.log', 'DVBridge native packed output failed'),
                ('.journal.log', 'Failed with result SIGKILL'),
                ('.shutdown.json', '{}')):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_planar_matrix(root)
                (root/('native-planar-2-flag1'+suffix)).write_text(content)
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_missing_or_extra_case_and_invalid_candidate_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_planar_matrix(root)
            with self.assertRaises(ValueError):
                aggregate(root, 'bad')
            extra = root/'native-planar-5-flag0.json'
            extra.write_text('{}')
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64)
            extra.unlink()
            (root/'native-planar-4-flag0.json').unlink()
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64)

    def test_startup_vs_steady_health_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_planar_matrix(root)
            result = aggregate(root, '0'*64)
            for condition in ('before', 'after'):
                for case in result[condition]['health_case_totals']:
                    self.assertEqual(case['raw_maximum_skip_total'], 1)
                    self.assertEqual(case['steady_skip_delta'], 0)

    def test_missing_changed_or_unrestored_subtitle_fixture_refused(self):
        edits = (
            lambda r: r.pop('subtitle_fixture'),
            lambda r: r['subtitle_fixture'].update(movie_id=51),
            lambda r: r['subtitle_fixture'].update(requested_enabled=True),
            lambda r: r['subtitle_fixture']['disabled'].update(enabled=True),
            lambda r: r['subtitle_fixture']['disabled_at_end'].update(enabled=True),
            lambda r: r['subtitle_fixture']['restored'].update(enabled=False),
            lambda r: r['subtitle_fixture']['before'].update(index=-1),
        )
        for edit in edits:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_planar_matrix(root)
                path = root/'native-planar-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_all_four_original_enabled_and_index_states_must_match(self):
        for enabled, index in ((False, 0), (True, 1)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_planar_matrix(root)
                path = root/'native-planar-3-flag1.json'
                raw = json.loads(path.read_text())
                original = dict(enabled=enabled, index=index)
                disabled = dict(enabled=False, index=index)
                raw['subtitle_fixture'].update(before=original.copy(), restored=original.copy(),
                    disabled=disabled.copy(), disabled_at_end=disabled.copy())
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_numeric_bool_aliases_in_subtitle_states_refused(self):
        for phase, key, value in (
                ('disabled', 'enabled', 0), ('disabled_at_end', 'enabled', 0),
                ('restored', 'enabled', 1), ('disabled', 'index', False),
                ('disabled_at_end', 'index', False), ('restored', 'index', False)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_planar_matrix(root)
                path = root/'native-planar-2-flag1.json'
                raw = json.loads(path.read_text())
                raw['subtitle_fixture'][phase][key] = value
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)


if __name__ == '__main__':
    unittest.main()
