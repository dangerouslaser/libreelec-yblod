"""Patch contract checks, not rendered-pixel or playback evidence."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[3]
PATCH=ROOT/'projects/Generic/patches/kodi/kodi-9999-yblod-06-native-reconstructed-input.patch'

class ReconstructedRendererPatch(unittest.TestCase):
    def test_explicit_bypass_and_unchanged_default_routes(self):
        text=PATCH.read_text()
        self.assertIn('mapped.dovi.comp[c].num_pivots=0;',text)
        self.assertIn('mapped.dovi.nlq_active=false;',text)
        self.assertIn('image.enhancement_layer=NULL;',text)
        self.assertIn('image.repr.alpha=PL_ALPHA_INDEPENDENT;',text)
        self.assertIn('packed || hdr10 || source->rotation',text)
        self.assertIn('geometry, NULL, false, false, NULL);',text)
        self.assertIn('geometry, NULL, false, true, NULL);',text)
        self.assertIn('geometry, target, flip, false, NULL);',text)
        self.assertIn('dvbridge_candidate_destroy(r->pending);',text)
        self.assertIn('alpha1 (caller invariant, not scanned by this entry point)',text)

    @unittest.skipUnless(os.environ.get('YBLOD_KODI_PATCH_BASELINE'),'set actual patched Kodi source for dry-run')
    def test_applies_to_actual_existing_renderer(self):
        source=Path(os.environ['YBLOD_KODI_PATCH_BASELINE'])
        self.assertTrue((source/'tools/dvbridge/dvbridge_render.c').is_file())
        with PATCH.open('rb') as patch:
            result=subprocess.run(['patch','--dry-run','--directory='+str(source),'-p1'],
                                  stdin=patch,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode())

if __name__=='__main__':unittest.main()
