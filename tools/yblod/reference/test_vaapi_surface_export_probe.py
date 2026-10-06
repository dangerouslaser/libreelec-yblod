"""Host-only structural validator and optional SDK CLI pre-device guards."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
HEADER = ROOT / "vaapi_surface_export_validation.h"


class DescriptorGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source = Path(cls.tmp.name) / "guard.c"
        source.write_text(r'''
#include "vaapi_surface_export_validation.h"
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv) {
 if(argc!=2) return 2;
 YbExportDescriptor d={0};int linear=-1;
 d.format=YB_FOURCC('P','0','1','0');d.width=d.height=4;d.objects=1;d.layers=2;
 d.obj[0].fd=17;d.obj[0].size=48;
 d.layer[0].format=YB_FOURCC('R','1','6',' ');d.layer[1].format=YB_FOURCC('G','R','3','2');
 for(unsigned i=0;i<2;++i) {d.layer[i].planes=1;d.layer[i].pitch[0]=8;}
 d.layer[1].offset[0]=32;
 int c=atoi(argv[1]);
 if(c>=28) {
   const int fds[4]={17,17,0,0};
   if(c==28) return yb_export_owned_fd_mask(1,fds)==1?0:1;
   if(c==29) return yb_export_owned_fd_mask(2,fds)==1?0:1;
   if(c==30) return yb_export_owned_fd_mask(0,fds)==0?0:1;
   if(c==31) return yb_export_owned_fd_mask(99,fds)==5?0:1;
   if(c==32) return yb_export_owned_fd_mask(1,NULL)==0?0:1;
 }
 switch(c) {
 case 1:d.objects=5;break;case 2:d.objects=0;break;case 3:d.layers=5;break;
 case 4:d.layer[0].planes=5;break;case 5:d.layer[0].object[0]=1;break;
 case 6:d.layer[0].offset[0]=48;break;case 7:d.layer[0].pitch[0]=7;break;
 case 8:d.layer[0].pitch[0]=UINT32_MAX;break;case 9:d.obj[0].size=47;break;
 case 10:d.layer[1].offset[0]=24;break;case 11:d.obj[0].fd=-1;break;
 case 12:d.width=0;break;case 13:d.layer[0].format=1;break;
 case 14:d.objects=2;d.obj[1]=d.obj[0];break;
 case 15:d.obj[0].modifier=1;break;
 case 16:d.format=YB_FOURCC('Y','4','1','6');d.layers=1;d.layer[0].format=d.format;d.layer[0].pitch[0]=32;d.obj[0].size=128;break;
 case 17:d.objects=2;d.obj[1]=d.obj[0];d.obj[1].fd=18;break;
 case 18:d.height=UINT32_MAX;break;case 19:d.obj[0].size=UINT32_MAX;break;
 case 20:d.layer[0].planes=0;break;case 21:d.layers=0;break;
 case 22:d.obj[0].modifier=1;d.layer[0].pitch[0]=0;break;
 case 23:d.format=1;break;case 24:d.obj[0].size=0;break;
 }
 int result=yb_export_validate(&d,d.format,&linear);
 if(c==25) result=yb_export_validate(NULL,d.format,&linear);
 if(c==26) result=yb_export_validate(&d,d.format,NULL);
 if(c==27) result=yb_export_validate(&d,YB_FOURCC('Y','4','1','6'),&linear);
 return result?(linear?0:3):1;
}
''')
        cls.binary = Path(cls.tmp.name) / "guard"
        subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT), str(source), "-o", str(cls.binary)], check=True, capture_output=True)

    def run_case(self, case):
        return subprocess.run([str(self.binary), str(case)], capture_output=True, timeout=5)

    def test_valid_linear_p010(self):
        self.assertEqual(self.run_case(0).returncode, 0)

    def test_valid_linear_y416(self):
        self.assertEqual(self.run_case(16).returncode, 0)

    def test_opaque_modifier_does_not_claim_linear_extents(self):
        self.assertEqual(self.run_case(15).returncode, 3)

    def test_malformed_descriptors(self):
        for case in [*range(1, 15), *range(17, 28)]:
            with self.subTest(case=case):
                result = self.run_case(case)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, b"")

    def test_owned_fd_selection_excludes_unused_and_deduplicates(self):
        for case in range(28, 33):
            with self.subTest(case=case):
                self.assertEqual(self.run_case(case).returncode, 0)


@unittest.skipUnless(os.environ.get("YBLOD_VAAPI_EXPORT_PROBE_BINARY"), "set YBLOD_VAAPI_EXPORT_PROBE_BINARY for SDK CLI guards")
class CliGuards(unittest.TestCase):
    def test_pre_device_rejections(self):
        binary = os.environ["YBLOD_VAAPI_EXPORT_PROBE_BINARY"]
        for args, expected in [((), "usage:"), (("x", "p010"), "explicit render node"), (("/dev/dri/card0", "p010"), "explicit render node"), (("/dev/dri/renderD128", "unknown"), "format must"), (("/dev/dri/renderD128x", "p010"), "explicit render node"), (("/dev/dri/renderD127", "p010"), "explicit render node")]:
            with self.subTest(args=args):
                result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("open render device", result.stderr)
                self.assertEqual(result.stdout, "")
