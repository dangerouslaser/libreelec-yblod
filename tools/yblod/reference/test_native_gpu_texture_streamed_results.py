"""Saved scalar uploaded-texture gate audit; no GPU or media access."""
import hashlib,json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
PATH=HERE/'results'/'native-gpu-texture-streamed-frame-checkpoint-20261005a.json'

class TextureResultsTests(unittest.TestCase):
    def setUp(self):self.r=json.loads(PATH.read_text())
    def test_source_pins(self):
        self.assertEqual(self.r['status'],'complete')
        for name,pin in self.r['provenance']['source_sha256'].items():
            self.assertEqual(hashlib.sha256((HERE.parents[2]/name).read_bytes()).hexdigest(),pin,name)
        self.assertEqual(self.r['provenance']['binary_sha256'],'747e0500eb80a4af69b616826acb2b6fb397c50eac5f3d7adc1f3d31e45cad09')
    def test_both_full_frame_gates_and_warm_scope(self):
        self.assertTrue(self.r['all_cpu_preflights_completed_before_gpu'])
        self.assertEqual([c['frame_label'] for c in self.r['runs']],['2296','1406'])
        for c in self.r['runs']:
            r=c['result'];self.assertEqual(r['status'],'complete')
            self.assertTrue(r['full_frame_gpu_exact']);self.assertTrue(r['cpu_full_frame_gate'])
            self.assertEqual((r['gpu_verified_dispatches'],r['gpu_oracle_dispatches'],r['gpu_verified_stage_values']),(48,191,49766400))
            self.assertEqual(r['timed_crosscheck_scope'],'final-CPU-subchunk-suffix-only')
            self.assertEqual((r['warm_readbacks_per_pass'],r['warm_readback_bytes']),(1,671744))
            self.assertEqual((r['observed_gl_error'],r['observed_egl_error']),(0,12288))
            self.assertTrue(r['device_binding_verified']);self.assertTrue(r['cleanup_succeeded'])
    def test_residency_setup_and_no_playback_claim(self):
        for c in self.r['runs']:
            r=c['result'];self.assertTrue(r['input_planes_resident'])
            self.assertTrue(r['texture_input_uploaded_checkpoint'])
            self.assertFalse(r['vaapi_zero_copy_import']);self.assertFalse(r['cpu_expanded_sample_ssbo'])
            self.assertEqual(r['warm_input_plane_uploads'],0)
            self.assertGreater(r['resident_texture_setup_wall_ns'],0)
            self.assertLessEqual(r['resident_texture_setup_wall_ns'],r['cold_setup_wall_ns'])
            self.assertFalse(r['dispatch_timing_is_device_kernel_time'])
        for k in ('real_time_playback','kodi_integration','vaapi_zero_copy_import','pure_kernel_timing','per_new_frame_preparation_upload_in_warm_timing'):
            self.assertFalse(self.r['claims'][k])
    def test_resources_and_unchanged_identity(self):
        self.assertTrue(self.r['kodi_unchanged']);self.assertTrue(self.r['private_inputs_runtime_unchanged'])
        for c in self.r['runs']:
            self.assertEqual(c['kodi_before'],c['kodi_after'])
            for key in ('resources_before','resources_after'):
                r=c[key];self.assertEqual(r['memory.max'],'536870912')
                self.assertEqual(r['memory.swap.max'],'0');self.assertEqual(r['memory.swap.current'],'0')
                self.assertLessEqual(int(r['memory.peak']),536870912)
                self.assertTrue(all(int(v.split()[1])==0 for v in r['memory.events'].splitlines()))

if __name__=='__main__':unittest.main()
