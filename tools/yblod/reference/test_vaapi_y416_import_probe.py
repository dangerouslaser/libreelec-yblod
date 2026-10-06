"""Host-only packed-word helpers and optional compiled CLI guards."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


def public_y416_words():
    """Byte-position oracle only; deliberately no Y/U/V/A semantics."""
    return tuple(17 + 997 * packed_word + 1231 * row
                 for row in range(4) for packed_word in range(16))


class PackedWordHelpers(unittest.TestCase):
    def test_saved_hardware_checkpoint(self):
        report=json.loads((ROOT/"results"/"vaapi-y416-packed-import-20261005c.json").read_text())
        result=report["result"]
        sample=result["egl_import"]
        self.assertEqual(result["object_layout"][0]["modifier"],72057594037927938)
        self.assertEqual((result["width"],result["height"],result["nominal_rt_bits"]),(4,4,12))
        self.assertTrue(sample["actual_shader_read"])
        self.assertEqual(sample["storage_words_compared"],64)
        self.assertEqual(sample["storage_word_mismatches"],0)
        self.assertEqual(tuple(sample["va_readback_storage_words"]),public_y416_words())
        self.assertEqual(sample["public_synthetic_storage_words"],sample["va_readback_storage_words"])
        self.assertEqual(sample["upload_vs_va_word_mismatches"],0)
        self.assertFalse(sample["packed_component_semantics_assumed"])
        self.assertFalse(result["dv_playback_tested"])
        self.assertFalse(result["zero_copy_proven"])
        for phase in ("before","after"):
            resources=report["resources"][phase]
            self.assertEqual(resources["memory.max"],"536870912")
            self.assertEqual(resources["memory.swap.max"],"0")
            self.assertEqual(resources["memory.swap.current"],"0")
            self.assertLessEqual(int(resources["memory.peak"]),536870912)
            self.assertTrue(all(int(line.split()[1])==0 for line in resources["memory.events"].splitlines()))

    def test_c_helpers_against_independent_position_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "guard.c"
            binary = Path(tmp) / "guard"
            source.write_text(r'''
#include <stdio.h>
#include "vaapi_y416_import_helpers.h"
int main(void){
 for(unsigned y=0;y<4;++y)for(unsigned x=0;x<16;++x)printf("%u\n",yb_y416_pattern(x,y));
 if(!yb_import_extension("A EGL_EXT_image_dma_buf_import B","EGL_EXT_image_dma_buf_import"))return 1;
 if(yb_import_extension("EGL_EXT_image_dma_buf_import_modifiers","EGL_EXT_image_dma_buf_import"))return 2;
 return 0;
}
''')
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT), str(source), "-o", str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
            self.assertEqual(tuple(map(int, result.stdout.split())), public_y416_words())

    def test_independent_anchors_cover_all_four_packed_positions(self):
        words = public_y416_words()
        self.assertEqual(len(words), 64)
        self.assertEqual(words[:8], (17, 1014, 2011, 3008, 4005, 5002, 5999, 6996))
        self.assertEqual(words[16:20], (1248, 2245, 3242, 4239))
        self.assertEqual(words[-4:], (15674, 16671, 17668, 18665))
        self.assertEqual(len(set(words)), 64)
        self.assertTrue(any(word & 15 for word in words))

    def test_separate_reference_and_sampling_comparisons(self):
        source = (ROOT / "vaapi_y416_import_probe.c").read_text()
        reader = (ROOT / "vaapi_y416_import_reader.h").read_text()
        self.assertIn("vaGetImage(display,surface,0,0,4,4,image.image_id)", source)
        self.assertIn("value!=yb_y416_pattern(x,y)", source)
        self.assertIn("words[i]!=va_reference_words[i]", reader)
        self.assertIn("internal_format!=GL_RGBA16", reader)
        self.assertIn("texelFetch(raw_plane,p,0)", reader)
        self.assertIn("round(v*65535.0)", reader)
        self.assertIn("YB_FOURCC('A','B','4','8')", reader)
        self.assertNotIn("texture(raw_plane", reader)
        self.assertNotIn("GL_RG16", reader)


@unittest.skipUnless(os.environ.get("YBLOD_VAAPI_Y416_IMPORT_PROBE_BINARY"), "set SDK binary for CLI guards")
class PackedCliGuards(unittest.TestCase):
    def test_pre_device_rejections(self):
        binary = os.environ["YBLOD_VAAPI_Y416_IMPORT_PROBE_BINARY"]
        for args, expected in [((), "usage:"), (("x", "y416"), "explicit render node"), (("/dev/dri/renderD128", "p010"), "format must be y416")]:
            with self.subTest(args=args):
                result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("open render device", result.stderr)
                self.assertEqual(result.stdout, "")
