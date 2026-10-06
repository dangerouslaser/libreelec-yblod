"""Structural guards for genuine context synthetic gate, not GPU evidence."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
class PlaybackContextRunnerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=(ROOT/'engine/experimental/native_playback_context_runner.c').read_text()
    def test_genuine_decoder_and_metadata_sources(self):
        s=self.source
        for call in ('av_hwdevice_ctx_create(','av_hwframe_ctx_init(','av_hwframe_get_buffer(','av_hwframe_transfer_data(','av_frame_new_side_data(frame,AV_FRAME_DATA_DOVI_METADATA','yb_playback_metadata_init(','yb_map_sample(','yb_compose('):self.assertIn(call,s)
        self.assertIn('frame.expanded_dovi_side_data=&metadata;',s)
        self.assertNotIn('yb_gpu_backend_submit(',s)
        self.assertNotIn('yb_gpu_ycc_submit(',s)
    def test_actual_orchestration_lifetime_and_restore(self):
        s=self.source
        for call in ('yb_native_playback_create(','yb_native_playback_submit(','yb_native_playback_finish(','yb_native_playback_release(','yb_native_playback_destroy('):self.assertIn(call,s)
        self.assertIn('av_buffer_get_ref_count(base->buf[0])!=base_refs+1',s)
        self.assertIn('av_buffer_get_ref_count(el->buf[0])!=el_refs+1',s)
        self.assertIn('memcmp(expected[fixture],actual,sizeof(actual))',s)
        self.assertGreaterEqual(s.count('!restored(display,context)'),7)
        self.assertIn('EGL_OPENGL_ES_API',s)
    def test_oracle_before_hardware_and_no_false_abandon(self):
        main=self.source.split('int main(',1)[1]
        self.assertLess(main.index('prepare_cpu(0)'),main.index('execute(argv[1]'))
        self.assertIn('"--validate"',main)
        self.assertNotIn('yb_native_playback_abandon_after_display_teardown(',self.source)
        self.assertIn('if(!playback){av_frame_free',self.source)
        self.assertIn('YB_NATIVE_PLAYBACK_FALLBACK',self.source)
if __name__=='__main__':unittest.main()
