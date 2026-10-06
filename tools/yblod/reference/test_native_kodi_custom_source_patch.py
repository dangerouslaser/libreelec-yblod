"""Generic08 source regressions only: not lock/runtime/hardware proof."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
PATCH=ROOT/'projects/Generic/patches/kodi/kodi-9999-yblod-08-custom-owned-source.patch'
def added_view(text):
    return '\n'.join(line[1:] for line in text.splitlines()
                     if line.startswith(('+',' ')) and not line.startswith('+++'))
class KodiCustomSourcePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch=PATCH.read_text()
        cls.files={}
        for section in cls.patch.split('--- a/')[1:]:
            name=section.splitlines()[0]
            cls.files[name]=added_view(section)
    def test_manual_actual_dovi_properties_without_decoder_ownership(self):
        s=self.files['xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.cpp']
        for guard in ('m_nativeSourceEnabled &&','m_vaapiConfig.pixelFormat == VA_FOURCC_P010','!(pic->DVDPic.iFlags & DVP_FLAG_INTERLACED)','av_buffer_get_opaque(pFrame->buf[0]) == this'):
            self.assertIn(guard,s)
        capture=s.split('const AVFrameSideData* dovi =',1)[1].split('m_bufferStats.IncDecoded()',1)[0]
        self.assertIn('av_frame_get_side_data(pFrame, AV_FRAME_DATA_DOVI_METADATA)',capture)
        self.assertIn('av_frame_new_side_data(source, AV_FRAME_DATA_DOVI_METADATA, dovi->size)',capture)
        self.assertIn('std::memcpy(copied->data, dovi->data, dovi->size)',capture)
        for field in ('pts','best_effort_timestamp','time_base','chroma_location','flags','color_primaries','color_trc','colorspace','color_range','format','width','height'):
            self.assertIn(f'source->{field} = pFrame->{field}',capture)
        self.assertIn('source->data[3] = pFrame->data[3]',capture)
        self.assertNotIn('av_frame_clone(',capture)
        self.assertNotIn('av_frame_copy_props(',capture)
        self.assertNotIn('private_ref',capture)
        self.assertNotIn('source->buf[',capture)
        self.assertNotIn('source->hw_frames_ctx',capture)
        self.assertNotIn('source->opaque_ref',capture)
        self.assertIn('pic->nativeSource.decoderOwner = this',capture)
        self.assertIn('pic->nativeSource.generation = m_nativeSourceGeneration',capture)
        self.assertIn('pic->nativeSource.poolState = m_nativePoolState',capture)
        self.assertIn('m_vaapiConfig.surfaceWidth',capture)
        self.assertIn('m_vaapiConfig.surfaceHeight',capture)
    def test_early_gfx_lock_and_actual_render_guard_lifetime(self):
        s=self.files['xbmc/cores/VideoPlayer/VideoRenderers/HwDecRender/RendererVAAPIGLES.cpp']
        render=s.split('bool CRendererVAAPIGLES::RenderDVBridge(',1)[1]
        self.assertLess(render.index('nativeGfxLock ='),render.index('auto* sourcePicture ='))
        self.assertLess(render.index('nativeGfxLock ='),render.index('pic->nativeSource.frame'))
        self.assertLess(render.index('std::unique_ptr<AVBufferRef, NativeGuardDeleter> nativeGuard'),render.index('pic->Acquire()'))
        self.assertLess(render.index('pic->Acquire()'),render.index('av_buffer_create(nullptr, 0, ReleaseNativeRenderOwner'))
        self.assertIn('void operator()(AVBufferRef* guard) const { av_buffer_unref(&guard); }',s)
        self.assertIn('picture->Release()',s)
        self.assertGreaterEqual(render.count('ValidateNativeRenderOwner(layer.nativeOwnerIdentity'),2)
        self.assertIn('return true;',render)
    def test_abi2_real_owner_and_generation_callbacks(self):
        s=self.files['xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp']
        self.assertIn('info.version = 2',s)
        for field in ('generation','owner_identity','render_guard','validate','mark_quarantine','allocation_width','allocation_height','va_display','fourcc'):
            self.assertIn('request.kodi_base.'+field,s)
        self.assertIn('request.base_storage = YB_NATIVE_BASE_KODI_SURFACE',s)
        owner=self.files['xbmc/cores/VideoPlayer/VideoRenderers/HwDecRender/RendererVAAPIGLES.cpp']
        for condition in ('owner->pool->valid.load()','owner->pool->quarantined.load()','owner->pool->generation != generation','source.poolState == owner->pool','source.generation == generation','owner->picture->procPic.videoSurface == surface','source.allocationWidth == width','source.allocationHeight == height'):
            self.assertIn(condition,owner)
        self.assertIn('owner->pool->quarantined.store(true)',owner)
        self.assertIn('CVaapiNativePoolState::processQuarantined.store(true)',owner)
    def test_pool_default_gate_invalidation_and_fail_closed_teardown(self):
        s=self.files['xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.cpp']
        h=self.files['xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.h']
        self.assertIn('bool m_nativeSourceEnabled = false',h)
        self.assertIn('native && std::strcmp(native, "1") == 0',s)
        self.assertIn('const std::uint64_t generation',h)
        self.assertIn('std::atomic<bool> valid{true}',h)
        self.assertIn('std::atomic<bool> quarantined{false}',h)
        self.assertIn('m_nativeSourceGeneration == std::numeric_limits<std::uint64_t>::max()',s)
        self.assertIn('std::make_shared<CVaapiNativePoolState>(m_nativeSourceGeneration)',s)
        fini=s.split('bool CDecoder::FiniVAAPIOutput()',1)[1]
        self.assertLess(fini.index('gfxLock ='),fini.index('quarantined.load()'))
        self.assertLess(fini.index('quarantined.load()'),fini.index('valid.store(false)'))
        self.assertLess(fini.index('valid.store(false)'),fini.index('m_vaapiOutput.Dispose()'))
        self.assertGreaterEqual(s.count('if (!FiniVAAPIOutput())'),2)
        self.assertIn('return CDVDVideoCodec::VC_FATAL',s)
    def test_reset_destructor_and_abandoned_pending_containment(self):
        s=self.files['xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp']
        destructor=s.split('CDVBridgeGLES::~CDVBridgeGLES()',1)[1].split('void CDVBridgeGLES::Reset()',1)[0]
        self.assertLess(destructor.index('if (!ReleaseNative())'),destructor.index('Summary("closed")'))
        reset=s.split('void CDVBridgeGLES::Reset()',1)[1]
        self.assertLess(reset.index('if (!ReleaseNative())'),reset.index('Summary("reset")'))
        self.assertLess(s.index('yb_native_playback_quarantine_retained(m_native)'),s.index('nativeCleanupRetained.store(true)'))
        self.assertIn('base.nativeValidate(base.nativeOwnerIdentity',s)
if __name__=='__main__':unittest.main()
