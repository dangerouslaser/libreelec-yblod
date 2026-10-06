"""Structural checks for proposed strict/custom synthetic gate, not GPU proof."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
class CustomContextRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=(ROOT/'engine/experimental/native_playback_custom_context_runner.c').read_text()
    def test_actual_fixture_owner_and_public_only_snapshot(self):
        s=self.source
        self.assertIn('owner->storage=av_frame_clone(base)',s)
        self.assertIn('owner_ref=av_buffer_create(NULL,0,owner_free,owner,0)',s)
        self.assertIn('frame.base_storage=YB_NATIVE_BASE_KODI_SURFACE',s)
        self.assertIn('if(fixture==1)',s)
        self.assertNotIn('av_frame_copy_props',s)
        self.assertNotIn('private_ref',s)
        self.assertIn('memcpy(out->data,side->data,side->size)',s)
    def test_both_lifetimes_and_full_oracle(self):
        s=self.source
        self.assertIn('base_refs+(fixture?0:1)',s)
        self.assertIn('av_buffer_get_ref_count(owner_ref)!=2',s)
        self.assertIn('av_buffer_get_ref_count(owner_ref)!=1',s)
        self.assertIn('owners_released!=1',s)
        self.assertIn('memcmp(expected[fixture],actual,sizeof(actual))',s)
        main=s.split('int main(',1)[1]
        self.assertLess(main.index('prepare_cpu(0)'),main.index('execute(argv[1]'))
    def test_failure_retains_before_any_teardown(self):
        s=self.source.split('cleanup:',1)[1]
        self.assertLess(s.index('yb_native_playback_quarantine_retained(playback)'),s.index('eglMakeCurrent('))
        self.assertIn('return 0;',s.split('yb_native_playback_quarantine_retained(playback)',1)[1].split('if(current',1)[0])
        self.assertIn('not Kodi pool',self.source)
if __name__=='__main__':unittest.main()
