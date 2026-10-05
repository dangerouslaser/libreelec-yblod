"""Host-only synthetic fixture/observer/runner checks; no GPU execution."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import native_texture_probe as probe

ROOT = Path(__file__).resolve().parent


def modeled_observation():
    report = probe.fixture()
    report.update(schema=probe.SCHEMA, status="observed", gpu_attempted=True,
        device_binding_verified=True, cleanup_succeeded=True, observed_gl_error=0,
        observed_egl_error=12288, fence_wait_result=37148, integer_control_mismatches=0,
        nonfinite_values=0, endpoint_mismatches=0, invalid_guard_flags=0, invalid_zero_controls=0,
        format_caps=dict(rgba16_supported=1, rgba16ui_supported=1, filter=33463))
    records = []
    for query in report["queries_i32"]:
        point = query[3]
        record = report["pixels_u16"][4*point:4*point+4] + [0]*32
        for component in range(4):
            values, flag = probe.sequential_model(report["pixels_u16"], query, component, report["parameters_u32"])
            for index, value in enumerate(values): record[4+4*index+component] = probe.bits(value)
            record[32+component] = flag
        records.append(record)
    report["records_u32"] = records
    return report


class TextureProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("cc") is None: raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temporary.name)/"texture-validate"
        command = ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                   "-fno-fast-math", "-ffp-contract=off", "-DYB_TEXTURE_PROBE_HOST_ONLY",
                   str(ROOT/"native_texture_probe.c"), "-o", str(cls.binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode: raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def test_native_fixture_matches_independent_python_fields(self):
        result = subprocess.run([str(self.binary), "--validate"], capture_output=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(probe.validate_fixture(report), probe.fixture())
        self.assertFalse(report["gpu_attempted"])
        self.assertEqual(report["parameters_u32"][2], 0x3f002008)
        self.assertEqual(probe.floating(report["parameters_u32"][3]), 0.249755859375)
        self.assertEqual(probe.floating(report["parameters_u32"][4]), -0.0001220703125)

    def test_grid_modes_point_control_and_fractional_filtered_index_are_separate(self):
        f = probe.fixture()
        self.assertEqual(f["count"], 112)
        self.assertEqual(len(f["pixels_u16"]), 64)
        self.assertEqual(set(q[2] for q in f["queries_i32"]), {0, 1})
        # logical4.5: integer fetch anchor4, nearest filtered5, linear4/5 average.
        q = [18, 0, 0, 4]
        self.assertEqual(probe.raw_sample(f["pixels_u16"], q, 1), 32769)
        q[2] = 1
        self.assertEqual(probe.raw_sample(f["pixels_u16"], q, 1), Fraction(65537, 2))
        self.assertEqual(probe.raw_sample(f["pixels_u16"], [-4, 0, 1, 0], 1), 0)
        self.assertEqual(probe.raw_sample(f["pixels_u16"], [34, 0, 1, 7], 1), 65535)

    def test_exact_parameters_do_not_mean_collapsed_sample_float_oracle(self):
        scale = probe.floating(probe.fixture()["parameters_u32"][1])
        self.assertNotEqual(probe.bits(probe.f32(probe.f32(Fraction(67, 65535))*scale)),
                            probe.bits(probe.f32(Fraction(67, 65472))))
        self.assertEqual(probe.ordered(0), probe.ordered(0x80000000))
        self.assertEqual(abs(probe.ordered(0xbf800000)-probe.ordered(0xbf800001)), 1)

    def test_sequential_model_analysis_is_observation_not_conformance(self):
        report = modeled_observation()
        result = probe.analyse(report)
        self.assertEqual(result["guard_branch_differences"], 0)
        self.assertTrue(all(v["bit_differences"] == 0 for v in result["sequential_binary32_comparison"].values()))
        # A finite result differing by one ULP is recorded, not rejected as an invented tolerance.
        report["records_u32"][0][12] += 1
        result = probe.analyse(report)
        self.assertEqual(result["sequential_binary32_comparison"]["scaled_el"]["bit_differences"], 1)

    def test_structural_control_and_zero_lane_failures(self):
        for change in (lambda d: d.update(count=True),
                       lambda d: d["records_u32"][0].__setitem__(0, 7),
                       lambda d: d["records_u32"][0].__setitem__(4, 0x7fc00001),
                       lambda d: d["records_u32"][0].__setitem__(19, probe.bits(1.)),
                       lambda d: d["records_u32"][0].__setitem__(35, 1),
                       lambda d: d.update(fence_wait_result=True),
                       lambda d: d.update(cleanup_succeeded=False),
                       lambda d: d["format_caps"].update(rgba16_supported=True)):
            d = modeled_observation(); change(d)
            with self.assertRaises(ValueError): probe.analyse(d)

    def test_guarded_zero_requires_zero_residual(self):
        d = modeled_observation()
        found = False
        for row in d["records_u32"]:
            for component in range(3):
                if row[32+component]:
                    row[28+component] = probe.bits(0.001); found = True; break
            if found: break
        self.assertTrue(found)
        with self.assertRaisesRegex(ValueError, "zero residual"): probe.analyse(d)

    def test_bounded_host_runner_and_source_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = probe.run(self.binary, ROOT/"native_texture_probe.comp", root/"run",
                               validate_only=True, require_memory_cap=False)
            self.assertEqual(report["status"], "validated")
            self.assertFalse(report["gpu_attempted"])
            with self.assertRaises(FileExistsError):
                probe.run(self.binary, ROOT/"native_texture_probe.comp", root/"run", validate_only=True, require_memory_cap=False)
            for name in probe.SOURCES: shutil.copyfile(ROOT/name, root/name)
            result = subprocess.run([sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,{str(root)!r});import native_texture_probe"],capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_memory_guard_and_strict_json(self):
        with mock.patch.object(probe, "memory", return_value={}):
            with self.assertRaisesRegex(ValueError, "512MiB"):
                probe.run("missing", "missing", "missing")
        for raw in ('{"a":1,"a":2}', '{"value":NaN}'):
            with self.assertRaises(ValueError): probe.strict_json(raw)


if __name__ == "__main__": unittest.main()
