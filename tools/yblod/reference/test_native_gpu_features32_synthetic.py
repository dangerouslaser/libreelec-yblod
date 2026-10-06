"""Public saved-evidence checks; no builds, GPU or media required."""
import hashlib
import json
import os
from pathlib import Path
import unittest

REFERENCE = Path(__file__).parent
ROOT = REFERENCE.parents[2]
GENERATOR = Path(os.environ.get('YB_FEATURES_GENERATOR', str(ROOT / 'engine/experimental/native_gpu_features32_fixture.c')))
CPU = Path(os.environ.get('YB_FEATURES_CPU_RESULT', str(REFERENCE / 'results/native-gpu-features32-synthetic-cpu-20261006.json')))
GPU = Path(os.environ.get('YB_FEATURES_GPU_RESULT', str(REFERENCE / 'results/native-gpu-features32-synthetic-gpu-20261006.json')))

class SyntheticFeatures(unittest.TestCase):
    def test_generator_pin_and_public_scope(self):
        cpu = json.loads(CPU.read_text())
        self.assertEqual(hashlib.sha256(GENERATOR.read_bytes()).hexdigest(), cpu['generator_sha256'])
        source = GENERATOR.read_text()
        self.assertIn('fopen(path,"wbx")', source)
        self.assertIn('const int32_t pivots[]={0,1,100,300,700,1023}', source)
        self.assertIn('segment->method=c?YB_MMR:YB_POLYNOMIAL', source)
        self.assertIn('sizeof(instruction)!=9216', source)
        self.assertNotIn('av_frame_copy_props', source)

    def test_cpu_cases_cover_orders_depths_and_separate_small_variant(self):
        cpu = json.loads(CPU.read_text())
        self.assertEqual(cpu['fixture_count'], 12)
        self.assertEqual(cpu['cpu_stage_values_total'], 294912)
        self.assertFalse(cpu['gpu_attempted'])
        expected = {(o,d,s) for o in (1,2,3) for d in (10,12) for s in (False,True)}
        self.assertEqual({(r['mmr_order'],r['output_depth'],r['small_slope']) for r in cpu['runs']}, expected)
        for run in cpu['runs']:
            self.assertEqual(run['status'], 'validated')
            self.assertEqual(run['cpu_stage_values'], 24576)

    def test_every_gpu_pair_counts_and_every_timing_sample(self):
        report = json.loads(GPU.read_text())
        self.assertEqual(report['gpu_job_count'], 24)
        self.assertEqual(report['cpu_stage_values_total'], 589824)
        self.assertEqual(report['gpu_reconstructed_codes_total'], 147456)
        self.assertFalse(report['performance_qualification'])
        self.assertFalse(report['candidate_adopted'])
        self.assertFalse(report['small_slope_stage_transition_histogram_measured'])
        expected = {(o,d,s,v) for o in (1,2,3) for d in (10,12) for s in (False,True) for v in ('baseline','candidate')}
        self.assertEqual({(r['mmr_order'],r['output_depth'],r['small_slope'],r['variant']) for r in report['runs']}, expected)
        for run in report['runs']:
            result = run['result']
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(result['full_frame_reconstructed_exact'])
            self.assertTrue(result['cleanup_succeeded'])
            self.assertEqual(result['gpu_verified_reconstructed_values'], 6144)
            self.assertEqual(result['cpu_stage_values'], 24576)
            self.assertEqual(result['gpu_verified_output_planes'], 3)
            for field in ('wall_ns','cpu_ns'):
                self.assertEqual(len(result[field]), 3)
                self.assertTrue(all(isinstance(x,int) and x>0 for x in result[field]))
            self.assertLess(run['memory_peak_bytes'], report['memory_limit_bytes'])
            self.assertTrue(run['memory_events_all_zero'])
            self.assertTrue(run['before_after_pins_match'])
            self.assertTrue(run['before_after_kodi_identity_startticks_match'])
            self.assertEqual(run['swap_bytes'], 0)
            throttle = run['cpu_throttling']
            self.assertEqual(throttle['nr_throttled_after'] - throttle['nr_throttled_before'], 0)
            self.assertEqual(throttle['throttled_usec_after'] - throttle['throttled_usec_before'], 0)

if __name__ == '__main__':
    unittest.main()
