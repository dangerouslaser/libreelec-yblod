import unittest
from summarize_playback_comparison import summarize


class PlaybackSummaryTests(unittest.TestCase):
    def report(self, lines):
        return dict(selected_log_lines=lines, label='test', elapsed_seconds=76,
                    kodi_before='same', kodi_after='same', failure_marker=False,
                    log_rotated_or_truncated=False)

    def test_subtracts_cumulative_weighted_totals(self):
        result = summarize(self.report([
            'DVBridge native timing: released_frames=120 valid=1 composer_wait=10.000',
            'DVBridge native timing: released_frames=240 valid=1 composer_wait=15.000',
        ]))
        self.assertEqual(result['stage_window']['wall_ms_per_release']['composer_wait'], 20)
        self.assertAlmostEqual(result['stage_window']['worst_case_log_rounding_error_ms'], .0015)

    def test_health_uses_logged_window_not_observer_seconds(self):
        result = summarize(self.report([
            'DVBridge playback health: interval_ms=10000 pts_s=10 drop_total=1 skip_total=2 counters_reset=false speed=1000 stalled=false render_avg_pct=50',
            'DVBridge playback health: interval_ms=10000 pts_s=70 drop_total=4 skip_total=6 counters_reset=false speed=1000 stalled=false render_avg_pct=60',
        ]))
        self.assertEqual(result['health']['source_seconds'], 60)
        self.assertEqual(result['health']['drop_delta'], 3)
        self.assertEqual(result['health']['skip_delta'], 4)
        self.assertEqual(result['health']['first_drop_total'], 1)
        self.assertEqual(result['health']['last_drop_total'], 4)
        self.assertEqual(result['health']['first_skip_total'], 2)
        self.assertEqual(result['health']['last_skip_total'], 6)
        self.assertEqual(result['health']['weighted_render_avg_percent'], 60)

    def test_reset_disqualifies_deltas(self):
        lines = ['DVBridge playback health: interval_ms=10000 pts_s=%s drop_total=0 skip_total=0 counters_reset=true speed=1000 stalled=false render_avg_pct=50' % n for n in (10,70)]
        result = summarize(self.report(lines))
        self.assertFalse(result['health']['counter_window_valid'])
        self.assertIsNone(result['health']['drop_delta'])


if __name__ == '__main__':
    unittest.main()
