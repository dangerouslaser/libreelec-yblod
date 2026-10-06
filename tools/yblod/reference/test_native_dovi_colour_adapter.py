"""Actual-header native adapter tests, synthetic metadata only; no GPU/media."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import colour_stage

ROOT = Path(__file__).resolve().parent
INCLUDE = os.environ.get("YBLOD_FFMPEG_INCLUDE_DIR")
SDK_BINARY = os.environ.get("YBLOD_DOVI_COLOUR_PROBE_BINARY")
IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def expected_config(case):
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
              signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
              signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 0 if i % 4 else 8192
        dm[f"rgb_to_lms_coef{i}"] = 0 if i % 4 else 16384
    for i in range(3):
        dm[f"ycc_to_rgb_offset{i}"] = 0
    if case == 1:
        dm["ycc_to_rgb_coef1"] = -799
        dm["rgb_to_lms_coef2"] = 267
    if case == 2:
        dm["ycc_to_rgb_offset1"] = 1 << 27
    if case == 3:
        dm["ycc_to_rgb_offset2"] = (2**31 - 1) * 2
    return colour_stage.ColourConfig.from_dm(
        dm, target_ycc=tuple(tuple(2 * x for x in row) for row in IDENTITY) if case == 34 else IDENTITY,
        target_lms=tuple(tuple(.5 * x for x in row) for row in IDENTITY) if case == 34 else IDENTITY,
        target_offset=(.1, .2, .3) if case == 34 else (0, 0, 0),
        pq_policy="reject-outside-unit" if case == 35 else "extend-positive-negative-to-zero", code_scale=4096)


EXPECTED_STATUS = {case: 3 for case in range(4, 14)}
EXPECTED_STATUS.update({case: 4 for case in range(14, 21)})
EXPECTED_STATUS.update({case: 5 for case in range(21, 25)})
EXPECTED_STATUS.update({25: 1, 26: 2, 27: 2, 28: 2, 29: 6, 30: 6, 31: 1, 32: 1, 33: 1})
EXPECTED_STATUS.update({36: 1, 37: 1, 38: 1, 39: 1, 40: 1, 41: 1, 42: 2, 43: 2, 44: 4})


@unittest.skipUnless(INCLUDE, "set YBLOD_FFMPEG_INCLUDE_DIR to actual matching FFmpeg headers")
class ColourAdapterActualHeader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (Path(INCLUDE) / "libavutil/dovi_meta.h").is_file():
            raise RuntimeError("actual dovi_meta.h required; no substitute ABI")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.binary = Path(cls.tmp.name) / "probe"
        # Expose only the actual FFmpeg headers; a whole SDK /usr/include on
        # host -I would shadow the host C library and is not a valid host ABI.
        header_root = Path(cls.tmp.name) / "headers"
        header_root.mkdir()
        (header_root / "libavutil").symlink_to(Path(INCLUDE) / "libavutil", target_is_directory=True)
        repo = ROOT.parents[2]
        build = subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fno-fast-math", "-ffp-contract=off", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-isystem", str(header_root), "-I", str(repo / "engine/include"), "-I", str(repo / "engine/experimental"), str(ROOT / "native_dovi_colour_adapter_probe.c"), str(ROOT / "native_dovi_colour_adapter.c"), str(repo / "engine/src/native_colour.c"), "-o", str(cls.binary), "-lm"], capture_output=True, text=True)
        if build.returncode:
            raise RuntimeError(build.stderr)

    def record(self, case, *, binary=None):
        result = subprocess.run([str(binary or self.binary), str(case)], check=True, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout, parse_constant=lambda value: self.fail(f"nonfinite {value}"))

    def validate(self, case, record):
        status = EXPECTED_STATUS.get(case, 0)
        self.assertEqual(record["schema"], "yblod.dovi-colour-adapter-synthetic.v1")
        self.assertEqual(record["case"], case)
        self.assertEqual(record["status"], status)
        self.assertTrue(record["inputs_unchanged"])
        if status:
            self.assertTrue(record["failure_output_untouched"])
            self.assertNotIn("source_ycc", record)
            return
        cfg = expected_config(case)
        for name in ("source_ycc", "source_lms", "target_ycc", "target_lms"):
            self.assertEqual(record[name], [x for row in getattr(cfg, name) for x in row])
        for name in ("source_offset", "target_offset"):
            self.assertEqual(record[name], list(getattr(cfg, name)))
        self.assertEqual(record["code_scale"], 4096)
        self.assertEqual(record["pq_policy"], 0 if case == 35 else 1)
        self.assertTrue(record["source_released_before_arithmetic"])
        self.assertEqual(record["sample_status"], 0)
        expected = colour_stage.convert_sample((2048, 1024, 3072), cfg)
        self.assertEqual(record["codes"], list(expected.codes))
        for name in ("source_nonlinear", "common_linear_lms"):
            for got, want in zip(record[name], getattr(expected, name)):
                self.assertTrue(math.isclose(got, want, rel_tol=1e-12, abs_tol=1e-15), (case, name, got, want))

    def test_supported_configs_match_independent_python_source_dm(self):
        for case in (0, 1, 2, 3, 34, 35):
            with self.subTest(case=case):
                self.validate(case, self.record(case))

    def test_failure_is_atomic_for_all_unsupported_inputs(self):
        for case in EXPECTED_STATUS:
            with self.subTest(case=case):
                self.validate(case, self.record(case))

    @unittest.skipUnless(SDK_BINARY, "set YBLOD_DOVI_COLOUR_PROBE_BINARY for strict SDK replay")
    def test_sdk_synthetic_records_match_host_and_python(self):
        for case in range(45):
            with self.subTest(case=case):
                host = self.record(case)
                sdk = self.record(case, binary=SDK_BINARY)
                self.validate(case, sdk)
                self.assertEqual(host, sdk)
