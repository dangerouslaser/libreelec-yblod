"""Host-only C parser tests. No libva, DRM device or GPU is required."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HARNESS = r'''
#include <stdio.h>
#include "drm_engine_accounting.h"

static void emit(EngineSample value)
{
    printf("{\"client_id\":");
    if (value.client_present) printf("%llu", value.client_id);
    else printf("null");
    printf(",\"pci_device\":");
    if (value.pci_device[0]) printf("\"%s\"", value.pci_device);
    else printf("null");
    for (unsigned i = 0; i < 4; ++i) {
        printf(",\"%s\":", engine_names[i]);
        if (value.present[i]) printf("%llu", value.ns[i]);
        else printf("null");
    }
    putchar('}');
}

int main(void)
{
    EngineSample samples[2] = {0};
    int valid[2] = {1, 1};
    unsigned phase = 0;
    char line[512];
    while (fgets(line, sizeof(line), stdin)) {
        if (!strcmp(line, "---\n")) { phase = 1; continue; }
        if (valid[phase] && !engine_parse_line(&samples[phase], line)) {
            valid[phase] = 0;
            memset(&samples[phase], 0, sizeof(samples[phase]));
        }
    }
    if (ferror(stdin)) return 2;
    printf("{\"valid\":[%d,%d],\"before\":", valid[0], valid[1]);
    emit(samples[0]);
    printf(",\"after\":");
    emit(samples[1]);
    printf(",\"delta\":");
    emit(engine_delta(samples[0], samples[1]));
    puts("}");
    return 0;
}
'''


class EngineAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="yblod-fdinfo-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / "test.c"
        source.write_text(HARNESS)
        cls.binary = directory / "test"
        compiled = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-I", str(Path(__file__).resolve().parent), str(source),
             "-o", str(cls.binary)],
            check=False, capture_output=True, text=True,
        )
        if compiled.returncode:
            raise AssertionError(
                f"host C harness compilation failed ({compiled.returncode}):\n"
                f"{compiled.stdout}{compiled.stderr}"
            )

    def run_fixture(self, before, after=""):
        result = subprocess.run(
            [str(self.binary)], input=before + "\n---\n" + after,
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    @staticmethod
    def identity(client=8, pci="0000:00:02.0"):
        return f"drm-client-id:\t{client}\ndrm-pdev:\t{pci}\n"

    def test_actual_vm_shape_and_all_classes(self):
        source = self.identity() + (
            "drm-driver:\ti915\n"
            "drm-engine-render:\t2844211636604 ns\n"
            "drm-engine-copy:\t0 ns\n"
            "drm-engine-video:\t42 ns\n"
            "drm-engine-capacity-video:\t2\n"
            "drm-engine-video-enhance:\t99 ns\n"
        )
        result = self.run_fixture(source)
        self.assertEqual(result["valid"], [1, 1])
        self.assertEqual(result["before"], {
            "client_id": 8, "pci_device": "0000:00:02.0",
            "render": 2844211636604, "copy": 0, "video": 42,
            "video-enhance": 99,
        })

    def test_missing_is_null_not_zero(self):
        result = self.run_fixture(self.identity())
        for key in ("render", "copy", "video", "video-enhance"):
            self.assertIsNone(result["before"][key])
            self.assertIsNone(result["delta"][key])

    def test_unsigned_boundaries(self):
        for value in (0, 18446744073709551615):
            with self.subTest(value=value):
                result = self.run_fixture(f"drm-engine-render: {value} ns\n")
                self.assertEqual(result["valid"][0], 1)
                self.assertEqual(result["before"]["render"], value)

    def test_malformed_unsigned_and_units(self):
        for text in ("-1 ns", "+1 ns", "18446744073709551616 ns",
                     "1", "1ns", "1 us", "1 nanoseconds", "1 ns junk",
                     "1.0 ns", "0x10 ns", "1e3 ns", "ns", ""):
            with self.subTest(text=text):
                result = self.run_fixture(f"drm-engine-render: {text}\n")
                self.assertEqual(result["valid"][0], 0)
                self.assertIsNone(result["before"]["render"])

    def test_client_has_no_unit_and_rejects_sign_overflow(self):
        for value in ("8 ns", "-1", "+1", "18446744073709551616", "8x"):
            with self.subTest(value=value):
                self.assertEqual(self.run_fixture(
                    f"drm-client-id: {value}\n")["valid"][0], 0)

    def test_duplicate_known_fields_invalidate_snapshot(self):
        for line in ("drm-client-id: 8\n", "drm-pdev: 0000:00:02.0\n",
                     "drm-engine-video-enhance: 9 ns\n"):
            with self.subTest(line=line):
                result = self.run_fixture(line + line)
                self.assertEqual(result["valid"][0], 0)
                self.assertTrue(all(value is None for value in result["before"].values()))

    def test_pci_rejects_unsafe_or_unbounded_value(self):
        for pci in ("", ".:", "0000:00:02.0 extra", '0000:00:02.0"',
                    "not-a-pci", "a" * 32):
            with self.subTest(pci=pci):
                self.assertEqual(self.run_fixture(
                    f"drm-pdev: {pci}\n")["valid"][0], 0)

    def test_known_key_without_colon_is_malformed(self):
        for line in ("drm-client-id 8\n", "drm-engine-video 8 ns\n", "drm-pdev\n"):
            with self.subTest(line=line):
                self.assertEqual(self.run_fixture(line)["valid"][0], 0)

    def test_unknown_fields_are_ignored_without_prefix_collision(self):
        source = ("drm-engine-capacity-video: 2\n"
                  "drm-engine-video-new-class: 22 ns\n"
                  "drm-driver: i915\n")
        result = self.run_fixture(source)
        self.assertEqual(result["valid"][0], 1)
        self.assertIsNone(result["before"]["video"])

    def test_delta_zero_increase_decrease_and_missing(self):
        before = self.identity() + (
            "drm-engine-render: 10 ns\ndrm-engine-copy: 20 ns\n"
            "drm-engine-video: 30 ns\ndrm-engine-video-enhance: 40 ns\n")
        after = self.identity() + (
            "drm-engine-render: 10 ns\ndrm-engine-copy: 27 ns\n"
            "drm-engine-video: 29 ns\n")
        self.assertEqual(self.run_fixture(before, after)["delta"], {
            "client_id": 8, "pci_device": "0000:00:02.0", "render": 0,
            "copy": 7, "video": None, "video-enhance": None,
        })

    def test_delta_requires_same_complete_identity(self):
        before = self.identity() + "drm-engine-render: 1 ns\n"
        for identity in (self.identity(client=9), self.identity(pci="0000:00:03.0"),
                         "drm-client-id: 8\n", "drm-pdev: 0000:00:02.0\n", ""):
            with self.subTest(identity=identity):
                result = self.run_fixture(before, identity + "drm-engine-render: 2 ns\n")
                self.assertTrue(all(value is None for value in result["delta"].values()))

    def test_whitespace_and_final_line_without_newline(self):
        result = self.run_fixture("", self.identity()
                                  + "drm-engine-render:\t 12\t ns \r\n"
                                  + "drm-engine-copy: 4 ns")
        self.assertEqual(result["valid"][1], 1)
        self.assertEqual(result["after"]["render"], 12)
        self.assertEqual(result["after"]["copy"], 4)


if __name__ == "__main__":
    unittest.main()
