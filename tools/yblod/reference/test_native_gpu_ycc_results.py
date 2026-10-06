"""Saved synthetic expansion checkpoint audit; no GPU execution."""
import hashlib
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
class GPUYCCResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=json.loads((ROOT/'results/native-gpu-ycc-image-synthetic-20261005q.json').read_text())
    def test_actual_api_exactness_and_negative_controls(self):
        r=self.report['result']
        self.assertTrue(r['complete'] and r['cleanup_complete'] and r['native_cpu_oracle_first'])
        self.assertEqual((r['float_bits_checked'],r['fixtures'],r['invalid_code_frame_rejections'],r['invalid_integer_filter_rejections']),(256,2,2,4))
        self.assertGreaterEqual(len(self.report['limitations']),3)
    def test_bounded_resources_and_identity(self):
        self.assertEqual(self.report['status'],'complete')
        self.assertTrue(self.report['kodi_unchanged'] and self.report['runtime_unchanged'])
        for key in ('resources_before','resources_after'):
            r=self.report[key]
            self.assertEqual(r['memory.max'],'536870912')
            self.assertEqual(r['memory.swap.max'],'0')
            self.assertEqual(r['memory.swap.current'],'0')
            self.assertLessEqual(int(r['memory.peak']),536870912)
            self.assertTrue(all(int(line.split()[1])==0 for line in r['memory.events'].splitlines()))
    def test_frozen_source_and_shader_provenance(self):
        pins=self.report['provenance']['source_sha256']
        self.assertEqual(len(pins),6)
        for path,pin in pins.items():self.assertEqual(hashlib.sha256((REPO/path).read_bytes()).hexdigest(),pin,path)
        self.assertEqual(self.report['shader_sha256'],pins['engine/experimental/native_gpu_reconstructed_ycc.comp'])
if __name__=='__main__':unittest.main()
