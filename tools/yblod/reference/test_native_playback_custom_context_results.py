"""Saved public strict/custom ABI2 GPU checkpoint audit; no GPU execution."""
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class CustomContextResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=json.loads((ROOT/'results/native-playback-custom-context-synthetic-20261006u.json').read_text())
    def test_exactness_and_scope(self):
        r=self.report['result'];c=self.report['cpu_preflight']
        self.assertTrue(r['complete'] and r['native_cpu_oracle_first'])
        self.assertEqual((r['rgba_float_bits_checked'],r['fixtures'],r['context_restore_checks']),(32768,2,12))
        self.assertTrue(r['strict_clone_and_custom_owner_lifetime_checked'] and r['association_rejection_checked'])
        self.assertEqual(c['rgba_float_bits_prepared'],32768)
        self.assertFalse(c['gpu_attempted'])
        self.assertEqual((r['guide_influenced_samples'],r['nonzero_residual_samples']),(4096,6144))
        self.assertIn('not Kodi pool',r['input_scope'])
        self.assertIn('not playback performance',self.report['evidence_scope'])
    def test_resource_and_identity_guards(self):
        before=self.report['before'];after=self.report['after']
        for name in ('pins','runtime','kodi'):self.assertEqual(before[name],after[name])
        for state in (before,after):
            r=state['resources']
            self.assertEqual((r['memory.max'],r['memory.swap.max'],r['memory.swap.current']),('536870912','0','0'))
            self.assertLessEqual(int(r['memory.peak']),536870912)
            self.assertTrue(all(int(line.split()[1])==0 for line in r['memory.events'].splitlines()))
    def test_separate_current_abi2_inventory(self):
        p=self.report['provenance']
        self.assertTrue(p['strict_sdk_compile'] and p['synthetic_inputs_public'])
        self.assertEqual(len(p['tested_source_sha256']),34)
        self.assertIn('engine/experimental/native_playback_custom_context_runner.c',p['tested_source_sha256'])
        self.assertNotIn('engine/experimental/native_playback_context_runner.c',p['tested_source_sha256'])
        for value in p['tested_source_sha256'].values():self.assertRegex(value,r'^[0-9a-f]{64}$')
        self.assertEqual(self.report['before']['pins']['native_playback_custom_context_runner'],'91e14019fd0f47f8c6d9f83752c7baffcd3a6e56d3de7928504cc5e3ee6c9e77')
if __name__=='__main__':unittest.main()
