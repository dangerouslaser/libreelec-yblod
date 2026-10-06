"""Adapter source-contract regressions only; no EGL or playback qualification."""
from pathlib import Path
import unittest


class AdapterFallbackContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[3]
        cls.patch = (root / 'packages/mediacenter/kodi/patches/kodi-9999-yblod-17-native-planar-output.patch').read_text()

    def test_flush_and_wrapper_destroy_before_materialize(self):
        block = self.patch.split('const auto materializeRGBA = [&]()', 1)[1].split('const bool planarGeometry', 1)[0]
        self.assertLess(block.index('pl_gpu_flush'), block.index('pl_tex_destroy'))
        self.assertLess(block.index('pl_tex_destroy'), block.index('yb_native_playback_materialize_rgba'))
        self.assertIn('attempt < 5 && status == YB_NATIVE_PLAYBACK_PENDING', block)
        self.assertIn('yb_native_playback_quarantine_retained', block)
        self.assertIn('nativeCleanupRetained.store(true)', block)

    def test_fallback_preserves_native_identity_and_format(self):
        block = self.patch.split('const auto materializeRGBA = [&]()', 1)[1].split('const bool planarGeometry', 1)[0]
        self.assertIn('std::memcmp(rgba.frame_id, association.frame_id, 32)', block)
        self.assertIn('rgba.width != association.width || rgba.height != association.height', block)
        self.assertIn('wrap.iformat = GL_RGBA32F', block)
        self.assertNotIn('yb_native_playback_submit', block)
        self.assertNotIn('yb_native_playback_release(', block)

    def test_post_completion_failure_cannot_select_legacy(self):
        self.assertIn('nativeCompleted = true;', self.patch)
        self.assertIn('m_nativeFailClosed = m_nativeFailClosed || (nativeCompleted && m_nativePlanar);', self.patch)
        self.assertEqual(self.patch.count('+  if (m_nativeFailClosed)\n+    return false;'), 2)
        self.assertIn('+  m_nativeFailClosed = false;', self.patch)

    def test_actual_route_not_configured_route_captured(self):
        self.assertIn('m_nativePlanarPrepared = planar != nullptr;', self.patch)
        self.assertIn('+        m_nativePrepared && m_nativePlanarPrepared ? 1 : 0', self.patch)
        self.assertNotIn('+        m_nativePrepared && m_nativePlanar ? 1 : 0', self.patch)

    def test_geometry_and_retry_use_same_native_composition(self):
        self.assertIn('const bool planarGeometry = !m_hdr10 && !geometry.x && !geometry.y', self.patch)
        self.assertIn('m_nativePlanar && (!planarReady || !planarGeometry)', self.patch)
        self.assertIn('if (!prepared && planarReady && !materialized)', self.patch)
        self.assertIn('Prepare(base, nullptr, metadata, geometry, allowPacked, reconstructed, &proof);', self.patch)

    def test_retry_preserves_committed_packet_history(self):
        block = self.patch.split('if (!prepared && planarReady && !materialized)', 1)[1].split('else if', 1)[0]
        self.assertIn('dvbridge_renderer_retry_native_colour(m_renderer)', block)
        self.assertNotIn('dvbridge_renderer_reset(', block)
        self.assertNotIn('dvbridge_reset(', block)
        cleanup = self.patch.split('+void dvbridge_renderer_retry_native_colour', 1)[1].split('\n+}', 1)[0]
        self.assertIn('dvbridge_candidate_destroy(r->pending)', cleanup)
        self.assertIn('pl_renderer_reset_errors', cleanup)
        self.assertNotIn('dvbridge_reset(', cleanup)


if __name__ == '__main__':
    unittest.main()
