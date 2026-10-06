"""Source-contract checks, not hardware/rendering qualification."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent
sys.argv = [sys.argv[0]]


def body(text, signature):
    start = text.index('{', text.index(signature))
    depth = 1
    for pos in range(start + 1, len(text)):
        depth += (text[pos] == '{') - (text[pos] == '}')
        if not depth:
            return text[start + 1:pos]
    raise AssertionError('unterminated function')


class SourceContract(unittest.TestCase):
    def test_importer_old_body_equivalent(self):
        old = (ROOT / 'renderer-baseline/VaapiEGL.cpp').read_text()
        new = (ROOT / 'VaapiEGL.cpp').read_text()
        substitutions = {'pic->vadsp': 'view.display',
                         'pic->procPic.videoSurface': 'view.surface',
                         'pic->DVDPic.iWidth': 'view.width',
                         'pic->DVDPic.iHeight': 'view.height',
                         'Import(pic)': 'Import(view)'}
        for name, original, replacement in (
                ('Import', 'bool CVaapi2Texture::Import(CVaapiRenderPicture* pic)',
                 'bool CVaapi2Texture::Import(const BorrowedSurfaceView& view)'),
                ('Get', 'CVaapi2Texture* CVaapiTexturePool::Get(CVaapiRenderPicture* pic,',
                 'CVaapi2Texture* CVaapiTexturePool::Get(const BorrowedSurfaceView& view,')):
            expected = body(old, original)
            for source, target in substitutions.items():
                expected = expected.replace(source, target)
            self.assertEqual(expected, body(new, replacement), name)

    def test_default_admission_requires_both_options(self):
        source = (ROOT / 'RendererVAAPIGLES.cpp').read_text()
        create = body(source, 'CBaseRenderer* CRendererVAAPIGLES::Create(')
        self.assertIn('getenv("DVBRIDGE_BASE_QSV")', create)
        self.assertIn('getenv("DVBRIDGE_NATIVE_RECONSTRUCTION")', create)
        self.assertIn('qsv->Valid(m_pWinSystem->GetVADisplay())', create)
        self.assertIn('return nullptr;', create)

    def test_no_legacy_fallback_for_typed_frame(self):
        source = (ROOT / 'DVBridgeGLES.cpp').read_text()
        prepare = body(source, 'bool CDVBridgeGLES::PrepareHardware(')
        self.assertIn('if (base.nativeOnly)', prepare)
        self.assertLess(prepare.index('qsv-base-native-required'), prepare.index('Quick Sync scaling'))
        self.assertLess(prepare.index('qsv-base-native-unavailable'), prepare.index('Quick Sync scaling'))

    def test_normal_preroll_does_not_quarantine(self):
        source = (ROOT / 'RendererVAAPIGLES.cpp').read_text()
        render = body(source, 'bool CRendererVAAPIGLES::RenderDVBridge(')
        self.assertNotIn('qsvPicture->Quarantine', render)
        source = (ROOT / 'DVBridgeGLES.cpp').read_text()
        self.assertNotRegex(source, r'if \(base\.nativeOnly\)\s*\{\s*m_nativeFailClosed\s*=')

    def test_typed_config_retains_parent_geometry_detection(self):
        source = (ROOT / 'RendererVAAPIGLES.cpp').read_text()
        config = body(source, 'bool CRendererVAAPIGLES::ConfigChanged(')
        branch = body(config, 'if (m_isQsvMappedBuffer || qsv)')
        self.assertIn('return true;', branch)
        self.assertIn('return CLinuxRendererGLES::ConfigChanged(picture);', branch)


if __name__ == '__main__':
    unittest.main()
