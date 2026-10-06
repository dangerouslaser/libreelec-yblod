import ast
from pathlib import Path
import unittest
from summarize_long_playback import summarize


class WindowTests(unittest.TestCase):
    def test_seek_payload_matches_observed_kodi_schema(self):
        tree = ast.parse(Path(__file__).with_name('observe_native_movie.py').read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'rpc'
                 and node.args and isinstance(node.args[0], ast.Constant)
                 and node.args[0].value == 'Player.Seek']
        self.assertEqual(len(calls), 1)
        payload = eval(compile(ast.Expression(calls[0].args[1]), '<seek-payload>', 'eval'),
                       {'__builtins__': {}}, {'active': [{'playerid': 1}], 'seconds': 1200})
        self.assertEqual(payload, {'playerid': 1, 'value': {'time': {
            'hours': 0, 'minutes': 20, 'seconds': 0, 'milliseconds': 0}}})

    def report(self):
        return {
            'selected_log_lines': [
                'DVBridge playback health: interval_ms=10000 pts_s=1202 drop_total=5 skip_total=6 counters_reset=false speed=1000 stalled=false render_avg_pct=50',
                'DVBridge playback health: interval_ms=10000 pts_s=1210 drop_total=7 skip_total=8 counters_reset=false speed=1000 stalled=false render_avg_pct=60',
                'DVBridge playback health: interval_ms=10000 pts_s=1220 drop_total=9 skip_total=11 counters_reset=false speed=1000 stalled=false render_avg_pct=70',
                'DVBridge native timing: valid=1 released_frames=120 composer_wait=10.000',
                'DVBridge native timing: valid=1 released_frames=240 composer_wait=12.000',
            ],
            'label': 'test', 'elapsed_seconds': 30, 'requested_seconds': 30,
            'seek_seconds': 1200, 'kodi_before': 'same', 'kodi_after': 'same',
            'failure_marker': False, 'log_rotated_or_truncated': False,
        }

    def test_seek_health_window_and_weighted_stage(self):
        result = summarize(self.report())
        self.assertEqual(result['health']['first_pts_s'], 1210)
        self.assertEqual(result['health']['drop_delta'], 2)
        self.assertEqual(result['health']['skip_delta'], 3)
        self.assertEqual(result['stage_window']['wall_ms_per_release']['composer_wait'], 14)

    def test_counter_reset_invalidates_delta(self):
        report = self.report()
        report['selected_log_lines'][2] = report['selected_log_lines'][2].replace(
            'counters_reset=false', 'counters_reset=true')
        self.assertIsNone(summarize(report)['health']['drop_delta'])

    def test_missing_gpu_and_player_samples_are_unavailable(self):
        result = summarize(self.report())
        self.assertEqual(result['gpu_counter_intervals']['valid_count'], 0)
        self.assertEqual(result['gpu_counter_intervals']['time_weighted_busy_percent'], {})
        self.assertFalse(result['player_progress']['all_normal_speed'])

    def test_counter_regression_invalidates_delta_even_without_reset_marker(self):
        report = self.report()
        report['selected_log_lines'][2] = report['selected_log_lines'][2].replace(
            'drop_total=9', 'drop_total=0')
        self.assertIsNone(summarize(report)['health']['drop_delta'])


if __name__ == '__main__':
    unittest.main()
