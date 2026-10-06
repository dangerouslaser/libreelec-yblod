"""Host source guard for retained decoder storage; no hardware execution."""
from pathlib import Path
import json
import unittest
ROOT=Path(__file__).resolve().parents[3]
class PlaybackFrameAdmissionTests(unittest.TestCase):
    def test_separate_actual_sdk_host_checkpoint_not_gpu_retest(self):
        p=json.loads((ROOT/'tools/yblod/reference/results/native-playback-frame-admission-host-20261005s.json').read_text())
        self.assertEqual(p['status'],'complete')
        self.assertTrue(p['strict_sdk_compile'])
        self.assertFalse(p['gpu_attempted'] or p['hardware_calls'] or p['gpu_retested'])
        self.assertEqual(p['sdk_runtime_replay']['checks'],3)
        self.assertTrue(p['sdk_runtime_replay']['missing_buf0_rejection_atomic'])
    def test_missing_retained_storage_is_rejected_before_device_inspection(self):
        s=(ROOT/'engine/experimental/native_playback_context.c').read_text().split('static int frame_contract(',1)[1].split('static int timebase_matches(',1)[0]
        self.assertIn('!frame->buf[0]',s)
        self.assertLess(s.index('!frame->buf[0]'),s.index('frame->hw_frames_ctx->data'))
        self.assertLess(s.index('!frame->buf[0]'),s.index('*allocated_w='))
    def test_actual_helper_replay_requires_positive_and_atomic_negative(self):
        s=(ROOT/'engine/experimental/native_playback_frame_admission_probe.c').read_text()
        self.assertIn('#include "native_playback_context.c"',s)
        self.assertIn('frame->buf[0]=NULL;width=31;height=37;',s)
        self.assertIn('!frame_contract(&context,frame,7,64,64,&width,&height)&&width==31&&height==37',s)
        self.assertIn('int okay=good&&rejected&&restored;',s)
        self.assertNotIn('eglCreate',s)
        self.assertNotIn('vaCreate',s)
if __name__=='__main__':unittest.main()
