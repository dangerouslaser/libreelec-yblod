"""Source contracts only; does not execute a Kodi decoder or GPU."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(sys.argv.pop(1))
SOURCE = (ROOT / 'DVDVideoCodecFFmpeg.cpp').read_text()

class Contracts(unittest.TestCase):
    def test_explicit_capability_before_open(self):
        self.assertLess(SOURCE.index('av_opt_find(m_pCodecContext->priv_data, "dovi_metadata"'),
                        SOURCE.index('avcodec_open2(m_pCodecContext'))
        self.assertIn('avcodec_find_decoder_by_name("hevc_qsv")', SOURCE)
        self.assertIn('std::getenv("DVBRIDGE_BASE_QSV")', SOURCE)
        self.assertIn('std::getenv("DVBRIDGE_NATIVE_RECONSTRUCTION")', SOURCE)

    def test_format_callback_preserves_device_identity(self):
        start = SOURCE.index('if (ctx && ctx->m_dvBaseQsv)')
        branch = SOURCE[start:SOURCE.index('const char* pixFmtName', start)]
        self.assertIn('avctx->hw_device_ctx->data != ctx->m_dvQsvDevice->data', branch)
        self.assertIn('return AV_PIX_FMT_NONE;', branch)
        self.assertNotIn('av_hwdevice_ctx_create', branch)
        self.assertNotIn('avcodec_default_get_format', branch)

    def test_device_display_has_owned_release(self):
        self.assertIn('CVAAPIContext::EnsureContext(&displayOwner, nullptr)', SOURCE)
        self.assertIn('device->user_opaque = displayOwner;', SOURCE)
        self.assertIn('context->user_opaque)->Release(nullptr)', SOURCE)

    def test_mapped_route_precedes_software_filters(self):
        mapped = SOURCE.index('auto* buffer = m_dvQsvPool->GetMapped(')
        self.assertLess(mapped, SOURCE.index('// process filters for sw decoding', mapped))
        self.assertIn('m_dvFailed = true;', SOURCE[mapped:mapped + 500])
        self.assertIn('GetPictureCommon(pVideoPicture)', SOURCE[mapped:mapped + 500])

    def test_el_receives_original_vaapi_device(self):
        self.assertIn('elDevice = m_dvVaapiDevice;', SOURCE)
        self.assertIn('dvbridge_fel_device(m_dvFel.get(), elDevice)', SOURCE)

    def test_reset_retires_generation(self):
        reset = SOURCE[SOURCE.index('void CDVDVideoCodecFFmpeg::Reset()'):]
        self.assertIn('m_dvQsvPool->Reset()', reset)
        self.assertIn('++m_dvQsvGeneration;', reset)
        self.assertIn('m_dvQsvMappedFrames == 1', SOURCE)
        self.assertIn('hardware = hardware || m_dvBaseQsv;', SOURCE)

    def test_buffer_implementation_in_non_dvbridge_vaapi_build(self):
        cmake = (ROOT / 'xbmc/cores/VideoPlayer/Buffers/CMakeLists.txt').read_text()
        self.assertIn('if(TARGET ${APP_NAME_LC}::VAAPI)', cmake)
        self.assertNotIn('ENABLE_DVBRIDGE', cmake)
        self.assertIn('list(APPEND SOURCES QsvMappedBuffer.cpp)', cmake)

if __name__ == '__main__':
    unittest.main()
