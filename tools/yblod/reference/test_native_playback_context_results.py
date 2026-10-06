"""Historical genuine-context synthetic checkpoint audit; no GPU."""
import json
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parent
class PlaybackContextResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=json.loads((ROOT/'results/native-playback-context-synthetic-20261005r.json').read_text())
    def test_genuine_end_to_end_exactness_and_lifetimes(self):
        p=self.report['result']
        self.assertTrue(p['complete'] and p['native_cpu_oracle_first'])
        self.assertEqual((p['rgba_float_bits_checked'],p['fixtures'],p['context_restore_checks']),(32768,2,12))
        self.assertGreater(p['guide_influenced_samples'],0)
        self.assertGreater(p['nonzero_residual_samples'],0)
        for name in ('actual_ffmpeg_va_frames','actual_expanded_dovi_metadata','decoder_clone_lifetime_checked','association_rejection_checked'):self.assertTrue(p[name])
        c=self.report['cpu_preflight']
        self.assertEqual(c['status'],'validated')
        self.assertFalse(c['gpu_attempted'])
        self.assertEqual(c['rgba_float_bits_prepared'],32768)
    def test_resources_and_identity(self):
        self.assertTrue(self.report['kodi_unchanged'] and self.report['runtime_unchanged'])
        for key in ('resources_before','resources_after'):
            p=self.report[key]
            self.assertEqual(p['memory.max'],'536870912')
            self.assertEqual(p['memory.swap.max'],'0')
            self.assertEqual(p['memory.swap.current'],'0')
            self.assertLessEqual(int(p['memory.peak']),536870912)
            self.assertTrue(all(int(line.split()[1])==0 for line in p['memory.events'].splitlines()))
    def test_historical_provenance_is_not_retroactively_repinned(self):
        p=self.report['provenance']
        self.assertEqual(len(p['tested_source_sha256']),34)
        for pin in p['tested_source_sha256'].values():self.assertRegex(pin,r'^[0-9a-f]{64}$')
        g=self.report['admission_guard_followup']
        self.assertEqual(g['tested_context_source_sha256'],p['tested_source_sha256']['engine/experimental/native_playback_context.c'])
        self.assertNotEqual(g['tested_context_source_sha256'],g['current_context_source_sha256'])
        self.assertFalse(g['gpu_retested'])
        self.assertIn('pre-guard',g['evidence_scope'])
        self.assertEqual(self.report['binary_sha256'],'bde8d21afdccc9fadd814c49dab8264fef94214e6d40708ac4defce555bf9aab')
if __name__=='__main__':unittest.main()
