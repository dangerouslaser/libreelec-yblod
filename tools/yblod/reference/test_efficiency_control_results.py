"""Saved sanitized control arithmetic audit; no playback or hardware calls."""
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class EfficiencyControlResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=json.loads((ROOT/'results/efficiency-control-20261006.json').read_text())
    def test_health_warmup_deltas_and_weighted_ranges(self):
        expected=[(8,11),(1,7)]
        for control,deltas in zip(self.report['controls'],expected):
            rows=control['health_rows'];steady=rows[1:]
            self.assertEqual((rows[-1]['drop_total']-rows[0]['drop_total'],rows[-1]['skip_total']-rows[0]['skip_total']),deltas)
            self.assertEqual((control['drop_delta'],control['skip_delta']),deltas)
            self.assertEqual(control['render_avg_pct_range'],[min(v['render_avg_pct'] for v in steady),max(v['render_avg_pct'] for v in steady)])
            duration=sum(v['interval_ms'] for v in steady)
            self.assertAlmostEqual(control['render_avg_pct_interval_wall_weighted'],sum(v['render_avg_pct']*v['interval_ms'] for v in steady)/duration)
            self.assertTrue(control['kodi_identity_unchanged'])
            self.assertFalse(control['failure_marker'])
    def test_gpu_capacity_normalization_uses_wall_not_frequency(self):
        g=self.report['gpu_summary']
        self.assertEqual((g['sample_start_index'],g['sample_end_index'],g['interval_count']),(4,34,30))
        self.assertEqual(g['elapsed_nanoseconds'],60309084027)
        for name,busy in g['engine_busy_nanoseconds_aggregate'].items():
            engine=g['engine'][name]
            self.assertAlmostEqual(engine['weighted_busy_percent'],100*busy/g['elapsed_nanoseconds']/engine['capacity'])
        self.assertEqual(g['engine']['drm-engine-video']['capacity'],2)
        self.assertEqual(g['frequency_sample_ranges_mhz']['gt_cur_freq_mhz'],[1200,1300])
        self.assertEqual(g['frequency_sample_ranges_mhz']['gt_act_freq_mhz'],[0,1300])
        self.assertTrue(g['frequency_not_used_as_utilization_denominator'])
        self.assertTrue(g['observer_start_monotonic_not_recorded'])
        self.assertTrue(g['new_observer_guards_not_retroactive_capture_evidence'])
    def test_scope_does_not_claim_after_gain_or_historical_match(self):
        self.assertTrue(self.report['historical_context']['historical_not_matched'])
        self.assertTrue(self.report['historical_context']['not_baseline_for_gain_inference'])
        l=self.report['limitations']
        for flag in ('raw_film_pixels_metadata_paths_or_hashes_published','raw_log_lines_published','hdmi_flips_measured','colour_accuracy_measured','optimization_gain_claim','matched_after_run_present'):
            self.assertFalse(l[flag])
        self.assertTrue(l['drop_skip_variation_already_present_between_controls'])
        self.assertTrue(l['observation_windows_not_total_playback_lengths'])
if __name__=='__main__':unittest.main()
