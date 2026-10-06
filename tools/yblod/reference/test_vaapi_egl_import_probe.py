"""GPU-free C helper/CLI guards for the isolated import experiment."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class ImportHelpers(unittest.TestCase):
    def test_exact_c_helpers_against_independent_public_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            source = path / "guard.c"
            source.write_text(r'''
#include <stdio.h>
#include "vaapi_egl_import_helpers.h"
int main(void){
 for(unsigned p=0;p<2;++p)for(unsigned y=0;y<(p?2u:4u);++y)for(unsigned x=0;x<4;++x)printf("%u\n",yb_import_expected_word(p,x,y));
 if(!yb_import_extension("A EGL_EXT_image_dma_buf_import B","EGL_EXT_image_dma_buf_import"))return 1;
 if(yb_import_extension("EGL_EXT_image_dma_buf_import_modifiers","EGL_EXT_image_dma_buf_import"))return 2;
 if(yb_import_extension(NULL,"A")||yb_import_extension("A",NULL)||yb_import_extension("A","")||yb_import_extension("A B","A B"))return 3;
 return 0;
}
''')
            binary = path / "guard"
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT), str(source), "-o", str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
            expected = [64,111,158,205,147,194,241,288,230,277,324,371,313,360,407,454,191,238,285,332,274,321,368,415]
            self.assertEqual([int(x) for x in result.stdout.split()], [x * 64 for x in expected])

    def test_source_has_no_colour_conversion_or_filtering(self):
        source = (ROOT / "vaapi_egl_import_reader.h").read_text()
        self.assertIn("texelFetch(raw_plane,p,0)", source)
        self.assertIn("round(v.r*65535.0)", source)
        self.assertNotIn("texture(raw_plane", source)
        self.assertIn("GL_R16", source)
        self.assertIn("GL_RG16", source)
        self.assertIn("GL_TIMEOUT_EXPIRED", source)
        self.assertIn("external_only[0]||external_only[1]", source)


@unittest.skipUnless(os.environ.get("YBLOD_VAAPI_EGL_IMPORT_PROBE_BINARY"), "set SDK binary for CLI guards")
class ImportCliGuards(unittest.TestCase):
    def test_reject_before_device_access(self):
        binary = os.environ["YBLOD_VAAPI_EGL_IMPORT_PROBE_BINARY"]
        for args, expected in [((), "usage:"), (("x", "p010"), "explicit render node"), (("/dev/dri/renderD128", "unknown"), "format must")]:
            with self.subTest(args=args):
                result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("open render device", result.stderr)
                self.assertEqual(result.stdout, "")
