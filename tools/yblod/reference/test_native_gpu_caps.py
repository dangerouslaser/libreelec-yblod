"""No GPU access: compile only pure guards/JSON helpers and audit forbidden calls."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class NativeGpuCapsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("host compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        source = root/"helpers.c"
        source.write_text('''#define YB_GPU_CAPS_UNIT_TEST
#include "native_gpu_caps.c"
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    if (!strcmp(argv[1],"node")) printf("%d",valid_node(argv[2]));
    else if (!strcmp(argv[1],"software")) printf("%d",software_renderer(argv[2]));
    else if (!strcmp(argv[1],"json")) json_string(argv[2]);
    else if (!strcmp(argv[1],"extension") && argc==4) printf("%d",has_extension(argv[2],argv[3]));
    else if (!strcmp(argv[1],"version") && argc==6)
        printf("%d",version_at_least(atoi(argv[2]),atoi(argv[3]),atoi(argv[4]),atoi(argv[5])));
    else return 2;
    return 0;
}
''')
        cls.executable = root/"helpers"
        result = subprocess.run(["cc","-std=c11","-O2","-Wall","-Wextra","-Werror",
            "-Wconversion","-Wshadow","-I",str(ROOT),str(source),"-o",str(cls.executable)],
            capture_output=True,text=True)
        if result.returncode: raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def call(self,*arguments):
        return subprocess.run([str(self.executable),*arguments],check=True,
                              capture_output=True,text=True).stdout

    def test_only_explicit_bounded_render_node_paths(self):
        for path in ("/dev/dri/renderD128","/dev/dri/renderD129","/dev/dri/renderD1048575"):
            self.assertEqual(self.call("node",path),"1")
        for path in ("/dev/dri/card0","/dev/dri/renderD127","/dev/dri/renderD",
                     "/dev/dri/renderD128/../card0","/dev/dri/renderD128x",
                     "/dev/dri/renderD1048576","/dev/dri/renderD99999999999999999",
                     "renderD128","/tmp/renderD128"):
            self.assertEqual(self.call("node",path),"0")

    def test_extension_exact_token_not_substring(self):
        name="EGL_EXT_device_query"
        for listing in (name,"AAA "+name,name+" BBB","AAA "+name+" BBB"):
            self.assertEqual(self.call("extension",listing,name),"1")
        for listing in ("",name+"_extra","X"+name,"EGL_EXT_device_quer"):
            self.assertEqual(self.call("extension",listing,name),"0")
        self.assertEqual(self.call("extension","AAA BBB","AAA BBB"),"0")

    def test_software_renderers_rejected_case_insensitively(self):
        for renderer in ("llvmpipe (LLVM 19)","SOFTPIPE","Software Rasterizer","swrast"):
            self.assertEqual(self.call("software",renderer),"1")
        for renderer in ("Mesa Intel(R) Xe Graphics (TGL GT2)","AMD Radeon RX"):
            self.assertEqual(self.call("software",renderer),"0")

    def test_separate_desktop_and_es_version_gates(self):
        for version,threshold,expected in (((4,2),(4,3),0),((4,3),(4,3),1),
                                           ((4,6),(4,3),1),((3,2),(4,3),0),
                                           ((3,0),(3,1),0),((3,2),(3,1),1)):
            self.assertEqual(self.call("version",*(str(v) for v in (*version,*threshold))),str(expected))

    def test_json_escaping(self):
        value='quotes" slash\\ newline\n tab\t control\x01'
        self.assertEqual(json.loads(self.call("json",value)),value)

    def test_no_workload_surface_or_kms_entrypoints(self):
        source=(ROOT/"native_gpu_caps.c").read_text()
        forbidden=("glDrawArrays","glDrawElements","glDispatchCompute","glCreateShader",
                   "glShaderSource","glCompileShader","glCreateProgram","glGenBuffers",
                   "glBufferData","glGenFramebuffers","glBindFramebuffer","eglSwapBuffers",
                   "eglCreateWindowSurface","eglCreatePbufferSurface","eglGetDisplay",
                   "drmModeSetCrtc","drmModeAtomicCommit")
        for name in forbidden:
            self.assertIsNone(re.search(r"\b"+name+r"\s*\(",source),name)
        self.assertIn("EGL_PLATFORM_DEVICE_EXT",source)
        self.assertIn("EGL_DRM_RENDER_NODE_FILE_EXT",source)
        self.assertIn("candidate.st_rdev == requested.st_rdev",source)


if __name__ == "__main__":
    unittest.main()
