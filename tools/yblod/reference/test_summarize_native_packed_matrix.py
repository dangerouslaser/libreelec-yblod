import json
from pathlib import Path
import tempfile
import unittest

from summarize_native_packed_matrix import aggregate, SHUTDOWN, STAGES
from test_native_packed_matrix import full_report


def write_matrix(root):
    durations = (1, 2, 4, 3)
    renders = (70, 60, 30, 50)
    for order, flag in enumerate((0, 1, 1, 0), 1):
        report, stopped = full_report(flag)
        report.update(media='Saving Private Ryan', movie_id=3391, seek_seconds=1200,
                      requested_seconds=180, expected_route='fp32', elapsed_seconds=180,
                      label=f'native-packed-{order}-flag{flag}')
        end_count = 480 if order < 3 else 840
        end_ms = 2 if not flag else order+1
        for count, average in ((120, 1), (end_count, end_ms)):
            report['selected_log_lines'].append('DVBridge native timing: '
                f'released_frames={count} valid=1 '+
                ' '.join(f'{name}={average:.3f}' for name in STAGES))
        for interval, pts, skips, speed in ((0, 1200, 0, 0), (5000, 1205, 1, 1000),
                                            (5000, 1210, 1, 1000), (5000, 1370, 1, 1000)):
            report['selected_log_lines'].append('DVBridge playback health: '
                f'interval_ms={interval} pts_s={pts} drop_total=0 skip_total={skips} '
                f'counters_reset=false speed={speed} stalled=false render_avg_pct=60')
        report['gpu_samples'][-1]['monotonic_ns'] = int((durations[order-1]+1)*1e9)
        report['gpu_intervals'] = [dict(elapsed_seconds=durations[order-1]/2,
            engine_busy_percent=dict(render=renders[order-1], video=5, video_enhance=10))
            for _ in range(2)]
        stem = report['label']
        (root/(stem+'.json')).write_text(json.dumps(report))
        (root/(stem+'.json.stop.json')).write_text(json.dumps(stopped))
        (root/(stem+'.shutdown.json')).write_text(json.dumps(SHUTDOWN))
        (root/(stem+'.journal.log')).write_text('kodi.service: Deactivated successfully.\n')
        (root/(stem+'.kodi.log')).write_text('qualified native playback\n')


class Tests(unittest.TestCase):
    def test_time_release_and_process_weighting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_matrix(root)
            report = aggregate(root, '0'*64)
            self.assertEqual(report['matrix'], [0, 1, 1, 0])
            self.assertEqual(report['before']['gpu_engine_busy_percent']['render'], 55)
            self.assertEqual(report['after']['gpu_engine_busy_percent']['render'], 40)
            self.assertAlmostEqual(report['before']['whole_kodi_cpu_percent_one_core'], 10)
            self.assertAlmostEqual(report['after']['whole_kodi_cpu_percent_one_core'], 100*.4/6)
            self.assertAlmostEqual(report['before']['helper_wall_ms_per_release']['composer_wait'], 2400/1080)
            self.assertAlmostEqual(report['after']['helper_wall_ms_per_release']['composer_wait'], 4560/1080)
            json.dumps(report, allow_nan=False)

    def test_startup_totals_are_not_steady_deltas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_matrix(root)
            report = aggregate(root, '0'*64)
            for case in report['cases']:
                self.assertEqual(case['raw_health']['maximum_observed_skip_total'], 1)
                self.assertEqual(case['health']['first_skip_total'], 1)
                self.assertEqual(case['health']['skip_delta'], 0)
                self.assertEqual(case['health']['drop_delta'], 0)

    def test_failed_shutdown_journal_and_fallback_rejected(self):
        for suffix, content in (('.shutdown.json', json.dumps(dict(SHUTDOWN, ExecMainStatus='1'))),
                                ('.journal.log', 'Main process exited status=9; Deactivated successfully'),
                                ('.journal.log', 'Stopped without clean lifecycle marker'),
                                ('.kodi.log', 'DVBridge native packed output failed; using composition'),
                                ('.kodi.log', 'DVBridge native reconstruction: fallback=release')):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                write_matrix(root)
                (root/('native-packed-2-flag1'+suffix)).write_text(content)
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_wrong_binary_scene_or_incomplete_matrix_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_matrix(root)
            with self.assertRaises(ValueError):
                aggregate(root, '1'*64)
            path = root/'native-packed-2-flag1.json'
            report = json.loads(path.read_text())
            report['media'] = '1917'
            path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                aggregate(root, '0'*64)
            write_matrix(root)
            (root/'native-packed-4-flag0.json').unlink()
            with self.assertRaises(FileNotFoundError):
                aggregate(root, '0'*64)

    def test_reset_or_invalid_stage_and_gpu_schema_rejected(self):
        edits = [lambda r: r.update(selected_log_lines=[
                    line.replace('released_frames=480', 'released_frames=120')
                    for line in r['selected_log_lines']]),
                 lambda r: r.update(selected_log_lines=[line.replace('valid=1', 'valid=0')
                                                        for line in r['selected_log_lines']]),
                 lambda r: r.update(selected_log_lines=[line.replace('ycc_wait=3.000', 'ycc_wait=nan')
                                                        for line in r['selected_log_lines']]),
                 lambda r: r['gpu_intervals'][1]['engine_busy_percent'].pop('video'),
                 lambda r: r.update(gpu_intervals=[])]
        for edit in edits:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                write_matrix(root)
                path = root/'native-packed-2-flag1.json'
                report = json.loads(path.read_text())
                edit(report)
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64)

    def test_steady_skips_and_stalls_are_preserved_in_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_matrix(root)
            path = root/'native-packed-2-flag1.json'
            report = json.loads(path.read_text())
            report['selected_log_lines'] = [line.replace('pts_s=1370 drop_total=0 skip_total=1',
                'pts_s=1370 drop_total=0 skip_total=2').replace(
                'pts_s=1370 drop_total=0 skip_total=2 counters_reset=false speed=1000 stalled=false',
                'pts_s=1370 drop_total=0 skip_total=2 counters_reset=false speed=1000 stalled=true')
                for line in report['selected_log_lines']]
            path.write_text(json.dumps(report))
            pooled = aggregate(root, '0'*64)['after']['health_case_totals'][0]
            self.assertEqual(pooled['steady_skip_delta'], 1)
            self.assertTrue(pooled['steady_stalled'])


if __name__ == '__main__':
    unittest.main()
