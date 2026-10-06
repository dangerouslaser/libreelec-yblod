"""Custom Kodi BL source guards; no hardware/runtime evidence inferred."""
from pathlib import Path
import json
import unittest
ROOT=Path(__file__).resolve().parents[3]
class KodiSnapshotSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'engine/experimental/native_playback_context.c').read_text()
        cls.header=(ROOT/'engine/experimental/native_playback_context.h').read_text()
    def test_explicit_version_and_strict_route_preserved(self):
        self.assertIn('info->version!=2',self.source)
        strict=self.source.split('static int frame_contract(',1)[1].split('static int base_contract(',1)[0]
        for text in ('!frame->buf[0]','frame->hw_frames_ctx->data','frames->sw_format!=AV_PIX_FMT_P010LE','device->type!=AV_HWDEVICE_TYPE_VAAPI'):
            self.assertIn(text,strict)
        self.assertIn('else p->base=av_frame_clone(frame->base_frame)',self.source)
    def test_manual_public_copy_without_ownership_transfer(self):
        copy=self.source.split('static AVFrame *copy_kodi_properties(',1)[1].split('int yb_native_playback_submit(',1)[0]
        self.assertNotIn('av_frame_copy_props',copy)
        self.assertNotIn('av_frame_clone',copy)
        self.assertNotIn('private_ref',self.source)
        for text in ('copy->pts=source->pts','copy->best_effort_timestamp=source->best_effort_timestamp','copy->time_base=source->time_base','copy->chroma_location=source->chroma_location','av_frame_new_side_data','memcpy(out->data,side->data,side->size)'):
            self.assertIn(text,copy)
    def test_explicit_callback_admission_and_quarantine(self):
        custom=self.source.split('static int base_contract(',1)[1].split('static int timebase_matches(',1)[0]
        for text in ('av_buffer_get_opaque(k->render_guard)!=k->owner_identity','!k->generation','!k->validate','!k->mark_quarantine','frame->opaque_ref','frame->hw_frames_ctx','frame->extended_buf','if (frame->buf[i])','k->validate(k->owner_identity'):
            self.assertIn(text,custom)
        quarantine=self.source.split('static void quarantine(',1)[1].split('static int finish_call(',1)[0]
        self.assertLess(quarantine.index('p->base_mark_quarantine('),quarantine.index('p->quarantined=1'))
        retained=self.source.split('int yb_native_playback_quarantine_retained(',1)[1].split('static int finish_call(',1)[0]
        self.assertIn('if (!p) return YB_NATIVE_PLAYBACK_ARGUMENT',retained)
        self.assertIn('quarantine(p)',retained)
        self.assertNotIn('egl',retained)
        self.assertNotIn('vaSync',retained)
    def test_release_order_and_host_probe_scope(self):
        release=self.source.split('static void release_decoded_refs(',1)[1].split('static int clear_frame(',1)[0]
        self.assertLess(release.index('av_frame_free(&p->base)'),release.index('av_buffer_unref(&p->base_render_guard)'))
        probe=(ROOT/'engine/experimental/native_playback_kodi_snapshot_probe.c').read_text()
        self.assertIn('#include "native_playback_context.c"',probe)
        self.assertIn('w==31 && h==37',probe)
        self.assertIn('!active->base && !active->el',probe)
        self.assertIn('NOT a',probe)
        self.assertNotIn('eglCreate',probe)
        self.assertNotIn('vaCreate',probe)
    def test_saved_host_checkpoint_is_not_gpu_proof(self):
        p=json.loads((ROOT/'tools/yblod/reference/results/native-playback-kodi-snapshot-host-20261006t.json').read_text())
        self.assertTrue(p['strict_sdk_compile'])
        self.assertFalse(p['gpu_attempted'] or p['hardware_calls'] or p['resource_counters_captured'])
        self.assertEqual(p['result']['checks_passed'],34)
        self.assertEqual(p['create_abi_version'],2)
        self.assertEqual(p['source_tests_passed'],13)
        self.assertEqual(len(p['tested_source_sha256']),4)
        for value in p['tested_source_sha256'].values():self.assertRegex(value,r'^[0-9a-f]{64}$')
if __name__=='__main__':unittest.main()
