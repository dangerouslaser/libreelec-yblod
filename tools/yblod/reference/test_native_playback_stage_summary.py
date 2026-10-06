import unittest
import json
from pathlib import Path
from native_playback_stage_summary import STAGES, summarize

class StageSummaryTests(unittest.TestCase):
    def test_saved_profile_scope_and_window_arithmetic(self):
        directory=Path(__file__).resolve().parent
        path=(directory/'results/native-playback-stage-profile-20261006.json'
              if directory.name=='reference' else directory/'NATIVE_PLAYBACK_STAGE_PROFILE_RESULTS.json')
        report=json.loads(path.read_text())
        self.assertFalse(report['optimization_applied'])
        native=report['measurement_build']['native_stages']
        self.assertEqual(len(native['stage_snapshots']),11)
        self.assertEqual(native['stage_snapshots'][-1]['released_frames'],1320)
        self.assertTrue(native['comparison_valid'])
        window=native['approximate_steady_stage_window']
        self.assertEqual(window['release_count_start_end'],[240,1200])
        self.assertAlmostEqual(window['per_stage_rounding_error_bound_ms_per_released_frame'],0.00075)
        a,b=native['stage_snapshots'][1],native['stage_snapshots'][9]
        for stage in STAGES:
            expected=(1200*b['rounded_cumulative_ms_per_released_frame'][stage]-240*a['rounded_cumulative_ms_per_released_frame'][stage])/960
            self.assertAlmostEqual(window['estimated_ms_per_released_frame'][stage],expected,places=12)
        for section,drop in (('baseline',1),('measurement_build',5)):
            self.assertEqual(report[section]['health']['drop_delta'],drop)
            self.assertEqual(report[section]['health']['skip_delta'],7)
        self.assertIn('not engine-only',report['service_memory']['scope'])
        self.assertIn('no demonstrated performance improvement',report['conclusion'])
        for marker in ('/storage/','/home/','/private/','MainPID=','T:'):
            self.assertNotIn(marker,path.read_text())
    def fixture(self, snapshots):
        lines=['2026-10-06 00:00:00.000 info DVBridge first frame: source=3840x2160']
        for seconds, count, mean in snapshots:
            lines.append(f'2026-10-06 00:00:{seconds:06.3f} info DVBridge native timing: released_frames={count} valid=1 wall_ms_per_released_frame '+ ' '.join(f'{s}={mean:.3f}' for s in STAGES))
        return dict(selected_log_lines=lines,failure_marker=False,kodi_before='identity',kodi_after='identity')
    def test_rounded_window_and_bound(self):
        result=summarize(self.fixture([(12,120,1),(36,360,2)]))
        window=result['approximate_steady_stage_window']
        self.assertEqual(window['release_count_start_end'],[120,360])
        self.assertEqual(window['estimated_ms_per_released_frame']['imports'],2.5)
        self.assertEqual(window['per_stage_rounding_error_bound_ms_per_released_frame'],0.001)
        self.assertNotIn("'identity'",str(result))
    def test_cumulative_only_and_count_reset(self):
        self.assertIn('stage_window_unavailable',summarize(self.fixture([(12,120,1)])))
        with self.assertRaises(ValueError):
            summarize(self.fixture([(12,120,1),(24,120,2)]))
    def test_invalid_means_counts_and_production_valid_marker(self):
        for marker in ('valid=0',):
            report=self.fixture([(12,120,1)])
            report['selected_log_lines'][1]=report['selected_log_lines'][1].replace('valid=1',marker)
            with self.assertRaises(ValueError): summarize(report)
        for mean in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError): summarize(self.fixture([(12,120,mean)]))
        for count in (0,119,121):
            with self.assertRaises(ValueError): summarize(self.fixture([(12,count,1)]))
    def test_identity_change_prevents_window_inference(self):
        report=self.fixture([(12,120,1),(36,360,2)])
        report['kodi_after']='changed'
        result=summarize(report)
        self.assertFalse(result['comparison_valid'])
        self.assertNotIn('approximate_steady_stage_window',result)

if __name__ == '__main__': unittest.main()
