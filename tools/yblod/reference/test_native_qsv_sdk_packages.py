"""CPU-only package contracts; no SDK/GPU/runtime or playback qualification."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from snapshot_native_ffmpeg_sdk import BASE, FAMILIES, snapshot

ROOT = Path(__file__).resolve().parents[3]
FFMPEG = ROOT / "packages/multimedia/ffmpeg/package.mk"


def load_feature(value=None, project="Generic", arch="x86_64", vaapi="yes"):
    env = os.environ.copy()
    env.update(PROJECT=project, TARGET_ARCH=arch, VAAPI_SUPPORT=vaapi,
               DISPLAYSERVER="gbm", V4L2_SUPPORT="no", FFMPEG_TESTING="no")
    if value is None:
        env.pop("YBLOD_QSV_DECODE", None)
    else:
        env["YBLOD_QSV_DECODE"] = value
    script = '''get_graphicdrivers() { :; }
get_pkg_directory() { printf '/package/%s' "$1"; }
build_with_debug() { return 1; }
target_has_feature() { return 1; }
die() { printf '%s\\n' "$*" >&2; exit 93; }
source "$1"
printf '%s\\n' "$PKG_FFMPEG_QSV" "$PKG_DEPENDS_TARGET" "$PKG_NEED_UNPACK" "$PKG_STAMP" "$PKG_BUILD_FLAGS" "$PKG_FFMPEG_LIBS"
'''
    return subprocess.run(["bash", "-c", script, "package-contract", str(FFMPEG)],
                          env=env, text=True, capture_output=True, timeout=10)


class Packages(unittest.TestCase):
    def test_default_equals_explicit_off(self):
        default, off = load_feature(), load_feature("no")
        self.assertEqual(default.returncode, 0)
        self.assertEqual(default.stdout, off.stdout)
        self.assertEqual(default.stdout.splitlines()[0], "")
        self.assertNotIn("libvpl", default.stdout)
        self.assertNotIn("vpl-gpu-rt", default.stdout)

    def test_on_is_explicit_and_stamp_distinct(self):
        on, off = load_feature("yes"), load_feature("no")
        self.assertEqual(on.returncode, 0, on.stderr)
        fields = on.stdout.splitlines()
        self.assertEqual(fields[0], "--enable-libvpl --enable-decoder=hevc_qsv")
        self.assertIn("libvpl vpl-gpu-rt", fields[1])
        self.assertIn("/package/libvpl /package/vpl-gpu-rt", fields[2])
        self.assertNotEqual(fields[3], off.stdout.splitlines()[3])
        self.assertIn("+bfd", fields[4])
        self.assertIn("-flto=1", fields[5])

    def test_bad_flag_rejected(self):
        for value in ("1", "true", "YES", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(load_feature(value).returncode, 93)

    def test_unsupported_admission_rejected(self):
        for project, arch, vaapi in (("RPi", "x86_64", "yes"),
                                    ("Generic", "aarch64", "yes"),
                                    ("Generic", "x86_64", "no")):
            with self.subTest(project=project, arch=arch, vaapi=vaapi):
                self.assertEqual(load_feature("yes", project, arch, vaapi).returncode, 93)

    def test_off_other_platform_unaffected(self):
        self.assertEqual(load_feature("no", "RPi", "aarch64", "no").returncode, 0)

    def test_runtime_uses_sdk_not_driver_replacement(self):
        rt = (ROOT / "packages/multimedia/vpl-gpu-rt/package.mk").read_text()
        self.assertIn('PKG_DEPENDS_TARGET="toolchain libva libdrm"', rt)
        self.assertIn('PKG_VERSION="26.3.5"', rt)
        self.assertIn("-DBUILD_KERNELS=OFF", rt)
        self.assertNotIn("scripts/build media-driver", rt)

    def test_new_packages_force_no_inherited_lto(self):
        for name in ("libvpl", "vpl-gpu-rt"):
            recipe = (ROOT / "packages/multimedia" / name / "package.mk").read_text()
            self.assertIn('PKG_BUILD_FLAGS="+bfd -lto -lto-fat +lto-off"', recipe)
            self.assertIn("-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF", recipe)

    def test_runtime_target_libgcc_link_contract(self):
        recipe = (ROOT / "packages/multimedia/vpl-gpu-rt/package.mk").read_text()
        self.assertIn('test "${CXX}" = "${TARGET_PREFIX}g++"', recipe)
        self.assertIn('$("${CXX}" -print-libgcc-file-name)', recipe)
        self.assertIn('"${TOOLCHAIN}"/lib/gcc/"${TARGET_NAME}"/*/libgcc.a', recipe)
        self.assertIn('-DCMAKE_CXX_STANDARD_LIBRARIES=${qsv_target_libgcc}', recipe)
        self.assertNotIn('-DCMAKE_SHARED_LINKER_FLAGS=', recipe)

    def test_failed_build_record_has_no_runtime_claim(self):
        import json
        report = json.loads(Path(__file__).with_name("NATIVE_QSV_SDK_FIRST_BUILD_RESULTS.json").read_text())
        self.assertEqual(report["exit_code"], 1)
        self.assertIs(report["runtime"]["built"], False)
        self.assertIs(report["ffmpeg_rebuild_reached"], False)
        self.assertEqual(report["resources"]["memory_events"]["oom"], 0)
        self.assertEqual(report["separate_baseline_archive_operation"]["memory_max_events"], 16)

    def test_recipe_limits_and_claims(self):
        script = Path(__file__).with_name("build_native_qsv_sdk.sh").read_text()
        for required in ("4294967296", "memory.swap.max", "CONCURRENCY_MAKE_LEVEL=1",
                         "CMAKE_BUILD_PARALLEL_LEVEL=1", "MAKEFLAGS=-j1", "DEFAULT_LINKER=bfd", "MTWITHLOCKS=no",
                         "existing_media_driver_unchanged=1", "qsv_runtime_discovery_qualified=0",
                         "kodi_playback_qualified=0"):
            self.assertIn(required, script)
        self.assertNotIn("ninja kodi", script)
        self.assertNotIn("Player.Open", script)

    def snapshot_fixture(self, root):
        base = root / BASE
        for path in (base / "build/ffmpeg-9.0.2", base / ".stamps/ffmpeg",
                     root / "packages/multimedia/ffmpeg"):
            path.mkdir(parents=True)
        (base / "build/ffmpeg-9.0.2/config.h").write_text("#define CONFIG_LIBVPL 0\n#define CONFIG_VAAPI 1\n")
        (base / ".stamps/ffmpeg/build_target").write_text("baseline stamp\n")
        (root / "packages/multimedia/ffmpeg/package.mk").write_text("baseline recipe\n")
        sdk = base / "toolchain/x86_64-libreelec-linux-gnu/sysroot/usr"
        (sdk / "lib/pkgconfig").mkdir(parents=True)
        for family in FAMILIES:
            (sdk / "include" / family).mkdir(parents=True)
            (sdk / "lib/pkgconfig" / (family + ".pc")).write_text("fixture pc\n")
            (sdk / "lib" / (family + ".so.1")).write_bytes(b"synthetic library")
            (sdk / "lib" / (family + ".so")).symlink_to(family + ".so.1")

    def test_snapshot_preserves_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.snapshot_fixture(root)
            archive = root / "baseline-ffmpeg-sdk.tar"
            result = snapshot(root, archive)
            self.assertIs(result["complete"], True)
            self.assertEqual(len(result["libraries"]), 16)
            self.assertIs(result["automatic_restore"], False)
            with self.assertRaises(ValueError):
                snapshot(root, archive)

    def test_snapshot_rejects_already_qsv_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.snapshot_fixture(root)
            (root / BASE / "build/ffmpeg-9.0.2/config.h").write_text("#define CONFIG_LIBVPL 1\n#define CONFIG_VAAPI 1\n")
            with self.assertRaises(ValueError):
                snapshot(root, root / "baseline-ffmpeg-sdk.tar")

    def test_snapshot_rejects_host_library_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.snapshot_fixture(root)
            bad = root / BASE / "toolchain/x86_64-libreelec-linux-gnu/sysroot/usr/lib/libavcodec.so"
            bad.unlink()
            bad.symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                snapshot(root, root / "baseline-ffmpeg-sdk.tar")


if __name__ == "__main__":
    unittest.main()
