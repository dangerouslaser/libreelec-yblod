"""Build-profile source checks; actual SDK compile/link evidence is separate."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3] / "engine"

class OptionalPlaybackProfile(unittest.TestCase):
    def test_default_stays_core_only(self):
        main = (ROOT/"CMakeLists.txt").read_text()
        self.assertRegex(main, r"option\(YBLOD_BUILD_EXPERIMENTAL_PLAYBACK\s+\"[^\"]*\" OFF\)")
        self.assertIn("if(YBLOD_BUILD_EXPERIMENTAL_PLAYBACK)", main)
        self.assertIn("include(cmake/ExperimentalPlayback.cmake)", main)
        self.assertIn("target_compile_options(yblod_native PRIVATE -fno-lto", main)
        self.assertIn("-Wl,--whole-archive yblod_playback_native yblod_native -Wl,--no-whole-archive", main)

    def test_real_complete_candidate_sources(self):
        module = (ROOT/"cmake/ExperimentalPlayback.cmake").read_text()
        sources = re.findall(r"experimental/(\w+\.c)\b", module)
        expected = {"native_dovi_adapter.c", "native_dovi_colour_adapter.c", "native_playback_metadata.c", "native_gpu_guard.c", "native_gpu_composer_backend.c", "native_gpu_preparation.c", "native_gpu_ycc_backend.c", "native_vaapi_el_scaler.c", "native_vaapi_gl_import.c", "native_egl_output_bridge.c", "native_playback_context.c"}
        self.assertEqual(set(sources), expected)
        self.assertEqual(len(sources), len(expected))
        for source in sources:
            self.assertTrue((ROOT/"experimental"/source).is_file(), source)
        self.assertIn("PkgConfig::YbNativeAvutil PkgConfig::YbNativeEgl PkgConfig::YbNativeVa", module)
        self.assertIn("C_EXTENSIONS NO", module)
        for flag in ("-fno-lto", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fno-fast-math", "-ffp-contract=off"):
            self.assertIn(flag, module)
        self.assertNotIn("HOST_ONLY", module)
        self.assertFalse(any(source.endswith("_probe.c") for source in sources))

    def test_installed_deps_and_real_link_guard(self):
        config = (ROOT/"cmake/YblodNativeConfig.cmake.in").read_text()
        self.assertIn("if(@YBLOD_BUILD_EXPERIMENTAL_PLAYBACK@)", config)
        for dep in ("YbNativeAvutil", "YbNativeEgl", "YbNativeVa"):
            self.assertIn("pkg_check_modules("+dep, config)
        smoke = (ROOT/"tests/native_playback_link_smoke.c").read_text()
        for call in ("yb_native_playback_create", "yb_vaapi_p010_import_create", "yb_gpu_preparation_create", "yb_gpu_ycc_create"):
            self.assertIn(call, smoke)
        self.assertNotIn("#define", smoke)

    def test_installed_abi_and_external_consumer(self):
        config = (ROOT/"cmake/YblodNativeConfig.cmake.in").read_text()
        self.assertIn('"libavutil>=@YBLOD_AVUTIL_ABI_MAJOR@.0.0"', config)
        self.assertIn('"libavutil<@YBLOD_AVUTIL_ABI_NEXT@.0.0"', config)
        module = (ROOT/"cmake/ExperimentalPlayback.cmake").read_text()
        self.assertIn('"${YbNativeAvutil_VERSION}"', module)
        self.assertIn('math(EXPR YBLOD_AVUTIL_ABI_NEXT', module)
        consumer = (ROOT/"tests/playback_consumer/CMakeLists.txt").read_text()
        self.assertIn("find_package(YblodNative 0.1 CONFIG REQUIRED)", consumer)
        self.assertIn("PRIVATE Yblod::yblod_playback_native", consumer)
        self.assertNotIn("target_include_directories", consumer)
