"""Public scalar-only balanced frame results; no GPU or private inputs."""
import hashlib,json
from pathlib import Path
import statistics
import unittest

HERE=Path(__file__).resolve().parent
PATH=HERE/'results'/'native-gpu-streamed-mmr-frame-comparison-20261005a.json'

class StreamedFrameResultsTests(unittest.TestCase):
    def setUp(self):self.report=json.loads(PATH.read_text())
    def test_public_source_pins(self):
        self.assertEqual(self.report['status'],'complete')
        root=HERE.parents[2]
        for name,pin in self.report['provenance']['source_sha256'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),pin,name)
        self.assertEqual(self.report['provenance']['binary_sha256'],'fc25316b58058f0d537cb1335ed64c54cbcf9fa5221fbe4f25733eca919ee8d9')
    def test_balanced_order_and_full_vs_warm_gates(self):
        runs=self.report['runs'];self.assertEqual(len(runs),8)
        self.assertTrue(self.report['all_cpu_preflights_completed_before_gpu'])
        for i,c in enumerate(runs):
            self.assertEqual(c['frame_label'],'2296' if i<4 else '1406')
            self.assertEqual(c['order'],i%4+1)
            self.assertEqual(c['variant'],('baseline','streamed','streamed','baseline')[i%4])
            r=c['result']
            self.assertTrue(r['full_frame_gpu_exact']);self.assertTrue(r['cpu_full_frame_gate'])
            self.assertEqual((r['gpu_verified_dispatches'],r['gpu_oracle_dispatches'],r['gpu_verified_stage_values']),(48,191,49766400))
            self.assertEqual(r['timed_crosscheck_scope'],'final-CPU-subchunk-suffix-only')
            self.assertEqual((r['golden_suffix_samples'],r['warm_readbacks_per_pass'],r['warm_readback_bytes']),(41984,1,671744))
            self.assertFalse(r['whole_frame_resident']);self.assertFalse(r['dispatch_timing_is_device_kernel_time'])
            self.assertEqual((r['observed_gl_error'],r['observed_egl_error']),(0,12288))
            self.assertTrue(r['cleanup_succeeded']);self.assertTrue(r['device_binding_verified'])
            for key in ('wall_ns','cpu_ns','dispatch_wall_ns','dispatch_cpu_ns'):
                self.assertEqual(len(r[key]),3);self.assertTrue(all(type(v)is int and v>=0 for v in r[key]))
    def test_medians_and_observed_separation(self):
        for frame,expected in (('2296',(637121785,401066458.5)),('1406',(615636248.5,355323079))):
            values={v:[n for c in self.report['runs'] if c['frame_label']==frame and c['variant']==v for n in c['result']['wall_ns']] for v in ('baseline','streamed')}
            self.assertEqual(tuple(statistics.median(values[v]) for v in ('baseline','streamed')),expected)
            self.assertLess(max(values['streamed']),min(values['baseline']))
    def test_resources_identity_and_no_overclaims(self):
        self.assertTrue(self.report['kodi_unchanged']);self.assertTrue(self.report['private_inputs_runtime_unchanged'])
        for c in self.report['runs']:
            self.assertEqual(c['kodi_before'],c['kodi_after'])
            for key in ('resources_before','resources_after'):
                r=c[key];self.assertEqual(r['memory.max'],'536870912')
                self.assertEqual(r['memory.swap.max'],'0');self.assertEqual(r['memory.swap.current'],'0')
                self.assertTrue(all(int(s.split()[1])==0 for s in r['memory.events'].splitlines()))
        for key in ('licensed_dolby_conformance','real_time_playback','kodi_integration','pure_kernel_timing','whole_frame_resident'):
            self.assertFalse(self.report['claims'][key])

if __name__=='__main__':unittest.main()
