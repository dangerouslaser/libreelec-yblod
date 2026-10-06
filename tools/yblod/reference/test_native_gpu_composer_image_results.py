"""Saved image-output checkpoint audit; no GPU execution."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]

class GPUComposerImageResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=json.loads((ROOT/'results/native-gpu-composer-image-frame-checkpoint-20261005p.json').read_text())

    def test_complete_final_code_oracle_and_honest_warm_scope(self):
        r=self.report
        self.assertEqual(r['status'],'complete')
        self.assertTrue(r['all_cpu_preflights_completed_before_gpu'])
        self.assertEqual([c['frame_label'] for c in r['cases']],['2296','1406'])
        for c in r['cases']:
            p=c['result']
            self.assertEqual(p['status'],'complete')
            self.assertTrue(p['full_frame_reconstructed_exact'])
            self.assertEqual((p['gpu_verified_output_planes'],p['gpu_oracle_dispatches'],p['gpu_verified_reconstructed_values']),(3,191,12441600))
            self.assertEqual((p['warm_plane_dispatches_per_pass'],p['warm_frame_completion_waits_per_pass'],p['warm_frame_error_readback_bytes']),(3,1,4))
            self.assertFalse(p['warm_reconstructed_code_check'])
            self.assertFalse(p['vaapi_zero_copy_import'])
            self.assertFalse(p['dispatch_timing_is_device_kernel_time'])
            self.assertEqual(p['timed_crosscheck_scope'],'frame-error-flag-only')
            for key in ('wall_ns','cpu_ns'):
                self.assertEqual(len(p[key]),3)
                self.assertTrue(all(type(v) is int and 0<v<5000000000 for v in p[key]))

    def test_resource_identity_and_cleanup_gates(self):
        r=self.report
        self.assertTrue(r['kodi_unchanged'] and r['private_inputs_runtime_unchanged'])
        for c in r['cases']:
            self.assertTrue(c['kodi_unchanged'] and c['private_inputs_and_runtime_unchanged'])
            p=c['result']
            self.assertTrue(p['device_binding_verified'] and p['cleanup_succeeded'])
            self.assertEqual((p['observed_gl_error'],p['observed_egl_error']),(0,12288))
            for k in ('resources_before','resources_after'):
                q=c[k]
                self.assertEqual(q['memory.max'],'536870912')
                self.assertEqual(q['memory.swap.max'],'0')
                self.assertEqual(q['memory.swap.current'],'0')
                self.assertLessEqual(int(q['memory.peak']),536870912)
                self.assertTrue(all(int(line.split()[1])==0 for line in q['memory.events'].splitlines()))

    def test_source_inventory_matches_checkpoint(self):
        pins=self.report['provenance']['source_sha256']
        self.assertEqual(len(pins),21)
        for path,pin in pins.items():
            self.assertEqual(hashlib.sha256((REPO/path).read_bytes()).hexdigest(),pin,path)

if __name__=='__main__':unittest.main()
