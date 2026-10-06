"""Scoped saved Kodi observations/regression audit; no playback/GPU commands."""
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class OwnedSourcePlaybackResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=json.loads((ROOT/'results/native-kodi-owned-source-playback-checkpoint-20261006.json').read_text())
    def test_candidate_and_reversible_install_provenance(self):
        p=self.report
        self.assertEqual(p['public_source_checkpoint'],'d6a5e65231b3b3e2d57d0db31de86ebe3c932b9b')
        self.assertEqual(p['build_report_commit'],'79c415ff64d40f4c616695d1661cee3caedc7b12')
        self.assertEqual(p['candidate_executable_sha256'],'b06db596c9cec559d5ea8634b6bdedcec0cf43bd376cb9be73529dada60c5931')
        i=p['installation']
        self.assertTrue(i['reversible_temporary_bind_mount'] and i['candidate_mount_and_active_binary_verified'] and i['original_squashfs_unchanged'])
        self.assertEqual(i['original_squashfs_sha256'],'884d6e922b130d28686095f836695df80d972c2ef2287f669264a56065595cd2')
        self.assertTrue(i['not_full_image_release'])
    def test_first_observation_markers_and_nonzero_drops(self):
        p=self.report['first_observation'];h=p['health_intervals']
        self.assertEqual(len(h),8)
        self.assertEqual((h[-1]['drop_total'],h[-1]['skip_total']),(2,5))
        self.assertEqual(h[-1]['pts_s'],70.153)
        self.assertEqual((p['native_presented_markers'][0],p['native_presented_markers'][-1]),(1,1560))
        self.assertTrue(p['kodi_identity_unchanged'])
        self.assertFalse(p['failure_marker_detected'])
        self.assertTrue(all(v['speed']==1000 and v['stalled']=='false' for v in h))
    def test_stop_restart_scope_does_not_invent_second_interval(self):
        p=self.report['stop_restart_observation'];h=p['health_intervals']
        self.assertTrue(p['playback_stopped_and_restarted_without_kodi_service_restart'] and p['kodi_identity_unchanged'])
        self.assertFalse(p['second_10_second_health_interval_captured'])
        self.assertEqual(len(h),2)
        self.assertEqual((h[-1]['drop_total'],h[-1]['skip_total'],h[-1]['render_avg_pct']),(2,2,62.4))
        self.assertEqual(p['native_presented_markers'],[1,120,240])
    def test_comparison_and_memory_scope(self):
        p=self.report;c=p['comparison']
        self.assertTrue(c['baseline_is_prior_separate_observation_not_paired_run'])
        self.assertEqual((c['existing_path_reported_drops'],c['existing_path_reported_skips']),(0,0))
        self.assertEqual(c['native_render_average_percent_range'],[66.1,74.2])
        self.assertGreater(c['native_render_average_percent_range'][0],c['existing_path_last_render_average_percent'])
        self.assertEqual(p['service_memory']['observed_peak_bytes'],1883865088)
        self.assertIn('NOT isolated native engine',p['service_memory']['scope'])
        cleanup=p['movie_cleanup']
        self.assertEqual(cleanup['active_players_after_both_stops'],[])
        self.assertEqual(cleanup['kodi_main_pid_after_both_stops'],37712)
        self.assertEqual(cleanup['final_service_memory_current_bytes'],817414144)
        self.assertTrue(cleanup['same_kodi_process_confirmed'])
        self.assertEqual((cleanup['both_renderer_reset_logs_presentation_failures'],cleanup['both_renderer_reset_logs_stage_failures']),(0,0))
        self.assertFalse(cleanup['native_fallback_or_retained_cleanup_markers_observed'] or cleanup['new_candidate_process_shutdown_tested'])
        self.assertIn('NOT leak-freedom',cleanup['memory_scope'])
    def test_full_regression_and_missing_dependency_attempt_distinct(self):
        r=self.report['regression'];m=r['resources'];first=r['initial_container_attempt']
        self.assertEqual((r['discovered_tests'],r['passed'],r['skipped'],r['failures'],r['errors']),(1322,1289,33,0,0))
        self.assertEqual((m['memory_limit_bytes'],m['swap_limit_bytes'],m['cpu_quota_percent']),(536870912,0,100))
        self.assertEqual(m['peak_bytes'],140251136)
        self.assertTrue(all(v==0 for v in m['memory_events'].values()))
        self.assertEqual(first['import_errors'],10)
        self.assertTrue(first['not_pass_evidence'] and first['retained_separately'])
        self.assertIn('NumPy',first['reason'])
    def test_no_display_colour_or_recovery_overclaim(self):
        s=self.report['scope']
        for name in ('hdmi_flip_timing_measured','perfect_cadence_claim','real_time_conformance_claim','colour_accuracy_measured','device_loss_recovery_tested','process_shutdown_tested','film_pixels_rpu_or_file_hashes_published'):
            self.assertFalse(s[name])
        self.assertTrue(s['output_attempts_are_not_display_flips'] and s['output_attempts_include_retries'])
        self.assertTrue(s['native_presented_counter_and_output_attempts_are_different_pipeline_points'])
        self.assertIn('NOT total playback run lengths',self.report['observation_duration_scope'])
        logs=self.report['first_observation']['selected_log_lines']+self.report['stop_restart_observation']['selected_log_lines']
        self.assertTrue(all('DVBridge' in line for line in logs))
        self.assertTrue(all('mkv' not in line.lower() and '/storage/' not in line for line in logs))
if __name__=='__main__':unittest.main()
