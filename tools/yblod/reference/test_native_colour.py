"""Temporary native builds; exact declared configuration, no hardware or film."""
import copy
import ctypes as C
from fractions import Fraction
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import colour_stage as oracle
from known_answers import COLOUR_INPUTS, identity_source_transport, pq_decode_unit, pq_encode_unit

IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
TARGET_YCC = ((8194/8192, 799/8192, 1681/8192),
              (8194/8192, -933/8192, 1091/8192),
              (8194/8192, 267/8192, -5545/8192))
TARGET_LMS = ((17080/16384, -348/16384, -348/16384),
              (-348/16384, 17080/16384, -348/16384),
              (-348/16384, -348/16384, 17080/16384))


class Parameters(C.Structure):
    _fields_ = [("source_ycc", C.c_double * 9), ("source_offset", C.c_double * 3),
                ("source_lms", C.c_double * 9), ("target_ycc", C.c_double * 9),
                ("target_offset", C.c_double * 3), ("target_lms", C.c_double * 9),
                ("pq_policy", C.c_int32), ("code_scale", C.c_int32)]


class Config(C.Structure):
    _fields_ = [("parameters", Parameters), ("target_ycc_inverse", C.c_double * 9),
                ("target_lms_inverse", C.c_double * 9), ("initialized", C.c_uint32)]


class Result(C.Structure):
    _fields_ = [("source_nonlinear", C.c_double * 3), ("common_linear_lms", C.c_double * 3),
                ("target_linear", C.c_double * 3), ("transport_before_quantization", C.c_double * 3),
                ("codes", C.c_uint16 * 3)]


def parameters(config):
    # Trusted test fixture conversion, not source-DM or JSON provenance parsing.
    result = Parameters()
    for name in ("source_ycc", "source_lms", "target_ycc", "target_lms"):
        getattr(result, name)[:] = [value for row in getattr(config, name) for value in row]
    for name in ("source_offset", "target_offset"):
        getattr(result, name)[:] = getattr(config, name)
    result.pq_policy = oracle.PQ_POLICIES.index(config.pq_policy)
    result.code_scale = config.code_scale
    return result


def python_config(*, source_ycc=IDENTITY, source_offset=(0, 0, 0), source_lms=IDENTITY,
                  target_ycc=TARGET_YCC, target_offset=(0, .5, .5), target_lms=TARGET_LMS,
                  policy="extend-positive-negative-to-zero"):
    return oracle.ColourConfig(source_ycc, source_offset, source_lms, target_ycc,
                               target_offset, target_lms, policy, 4096)


class NativeColourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise RuntimeError("native colour tests require a C11 compiler and libm")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        here = Path(__file__).resolve().parent
        library = Path(cls.temporary.name) / "libnative_colour.so"
        cls.compiler_version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
        subprocess.run([compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
                        "-Wconversion", "-Wshadow", "-fno-fast-math", "-ffp-contract=off",
                        str(here / "native_colour.c"), "-lm", "-o", str(library)],
                       check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(library))
        for name, arguments in {
            "yb_colour_init": [C.POINTER(Parameters), C.POINTER(Config)],
            "yb_colour_validate": [C.POINTER(Config)],
            "yb_pq_decode": [C.c_double, C.c_int32, C.POINTER(C.c_double)],
            "yb_pq_encode": [C.c_double, C.c_int32, C.POINTER(C.c_double)],
            "yb_colour_sample": [C.POINTER(Config), C.POINTER(C.c_double), C.POINTER(Result)],
            "yb_colour_process_chunk": [C.POINTER(Config), C.POINTER(C.c_double), C.c_uint32,
                                         C.c_uint32, C.POINTER(Result), C.c_uint32],
        }.items():
            function = getattr(cls.lib, name)
            function.argtypes, function.restype = arguments, C.c_int
        cls.lib.yb_colour_abi_version.argtypes, cls.lib.yb_colour_abi_version.restype = [], C.c_uint32
        for name in ("yb_sizeof_colour_parameters", "yb_sizeof_colour_config", "yb_sizeof_colour_result"):
            getattr(cls.lib, name).argtypes, getattr(cls.lib, name).restype = [], C.c_uint64

    def native_config(self, python):
        compiled = Config()
        values = parameters(python)
        self.assertEqual(self.lib.yb_colour_init(C.byref(values), C.byref(compiled)), 0)
        return compiled

    def assert_result(self, actual, expected):
        self.assertEqual(tuple(actual.codes), expected.codes)
        for name in ("source_nonlinear", "common_linear_lms", "target_linear", "transport_before_quantization"):
            for value, wanted in zip(getattr(actual, name), getattr(expected, name)):
                self.assertTrue(math.isclose(value, wanted, rel_tol=2e-11, abs_tol=2e-12), (name, value, wanted))

    def test_abi_queries_pq_against_independent_decimal_answers(self):
        self.assertEqual(self.lib.yb_colour_abi_version(), 1)
        for name, structure in (("parameters", Parameters), ("config", Config), ("result", Result)):
            self.assertEqual(getattr(self.lib, "yb_sizeof_colour_" + name)(), C.sizeof(structure))
        for value in (Fraction(0), Fraction(1, 1000000), Fraction(1, 100), Fraction(1, 2), Fraction(1)):
            for function, expected in ((self.lib.yb_pq_decode, pq_decode_unit(value)),
                                       (self.lib.yb_pq_encode, pq_encode_unit(value))):
                output = C.c_double(12345)
                self.assertEqual(function(float(value), 0, C.byref(output)), 0)
                self.assertAlmostEqual(output.value, float(expected), delta=2e-13)

    def test_pq_policies_negative_positive_extension_pole_and_no_failed_write(self):
        for name in ("decode", "encode"):
            function = getattr(self.lib, "yb_pq_" + name)
            for value, policy in ((-1, 0), (1.2, 0), (math.nan, 1), (math.inf, 1), (.5, 2)):
                output = C.c_double(12345)
                self.assertNotEqual(function(value, policy, C.byref(output)), 0)
                self.assertEqual(output.value, 12345)
            negative, zero, positive = C.c_double(), C.c_double(), C.c_double()
            self.assertEqual(function(-1, 1, C.byref(negative)), 0)
            self.assertEqual(function(0, 1, C.byref(zero)), 0)
            self.assertEqual(negative.value, zero.value)
            self.assertEqual(function(1.2, 1, C.byref(positive)), 0)
            self.assertGreater(positive.value, 1)
            self.assertNotEqual(function(.5, 0, None), 0)
        output = C.c_double(12345)
        self.assertNotEqual(self.lib.yb_pq_decode(100, 1, C.byref(output)), 0)
        self.assertEqual(output.value, 12345)

    def test_source_variants_intermediates_fractional_chroma_and_transport_codes(self):
        samples = [(i * 17 % 4096, i * 31 % 4096, i * 47 % 4096) for i in range(256)]
        samples += list(COLOUR_INPUTS.values())
        samples += [(2048, Fraction(1023, 2), Fraction(6145, 2)), (4095, .25, 4094.75)]
        variants = [python_config(),
                    python_config(source_ycc=((1, -.0625, 0), (0, 1, 0), (0, 0, 1)),
                                  source_offset=(.0625, 0, 0), source_lms=((1, 0, 0), (.015625, 1, 0), (0, 0, 1))),
                    python_config(source_ycc=((12000/8192, 0, 0), (0, 1, 0), (0, 0, 1)),
                                  source_lms=((1, -128/16384, 0), (0, 1, 0), (0, 0, 1)))]
        for python in variants:
            compiled = self.native_config(python)
            for sample in samples:
                output = Result()
                self.assertEqual(self.lib.yb_colour_sample(C.byref(compiled), (C.c_double * 3)(*sample), C.byref(output)), 0)
                self.assert_result(output, oracle.convert_sample(sample, python))
        python = python_config(policy="reject-outside-unit")
        compiled = self.native_config(python)
        for values in COLOUR_INPUTS.values():
            output = Result()
            self.assertEqual(self.lib.yb_colour_sample(C.byref(compiled), (C.c_double * 3)(*values), C.byref(output)), 0)
            self.assertEqual(tuple(output.codes), identity_source_transport(values))

    def test_inverse_once_explicit_offsets_and_final_only_bound(self):
        target = ((1, 2, 0), (0, 1, 3), (0, 0, 1))
        python = python_config(target_ycc=target, target_offset=(0, 0, 0), target_lms=IDENTITY,
                               policy="reject-outside-unit")
        compiled = self.native_config(python)
        self.assertEqual(list(compiled.target_ycc_inverse), [1, -2, 6, 0, 1, -3, 0, 0, 1])
        output = Result()
        self.assertEqual(self.lib.yb_colour_sample(C.byref(compiled), (C.c_double * 3)(0, 4095, 0), C.byref(output)), 0)
        self.assert_result(output, oracle.convert_sample((0, 4095, 0), python))
        self.assertLess(output.transport_before_quantization[0], -1.9)
        self.assertEqual(tuple(output.codes), (0, 4095, 0))
        params = parameters(python)
        self.assertEqual(self.lib.yb_colour_init(C.byref(params), C.byref(compiled)), 0)
        params.source_ycc[0] = 100
        self.assertEqual(compiled.parameters.source_ycc[0], 1)

    def test_configuration_input_and_nonfinite_domain_validation(self):
        python = python_config()
        good = parameters(python)
        for field, value in (("pq_policy", -1), ("pq_policy", 2), ("code_scale", 4095), ("code_scale", 0)):
            params = copy.deepcopy(good); setattr(params, field, value)
            config = Config(); C.memset(C.byref(config), 0xA5, C.sizeof(config))
            before = bytes(config)
            self.assertNotEqual(self.lib.yb_colour_init(C.byref(params), C.byref(config)), 0)
            self.assertEqual(bytes(config), before)
        for name in ("source_ycc", "source_offset", "source_lms", "target_ycc", "target_offset", "target_lms"):
            params = copy.deepcopy(good); getattr(params, name)[0] = math.nan
            self.assertNotEqual(self.lib.yb_colour_init(C.byref(params), C.byref(Config())), 0)
        for matrix in ((0,) * 9, (1, 0, 0) * 3, (1e308,) * 9):
            params = copy.deepcopy(good); params.target_ycc[:] = matrix
            self.assertNotEqual(self.lib.yb_colour_init(C.byref(params), C.byref(Config())), 0)
        compiled = self.native_config(python)
        for sample in ((-1, 0, 0), (4096, 0, 0), (0, math.inf, 0), (math.nan, 0, 0)):
            result = Result(); C.memset(C.byref(result), 0xA5, C.sizeof(result)); before = bytes(result)
            self.assertNotEqual(self.lib.yb_colour_sample(C.byref(compiled), (C.c_double * 3)(*sample), C.byref(result)), 0)
            self.assertEqual(bytes(result), before)
        bad = copy.deepcopy(compiled); bad.target_lms_inverse[0] = math.nan
        self.assertNotEqual(self.lib.yb_colour_validate(C.byref(bad)), 0)
        self.assertNotEqual(self.lib.yb_colour_validate(C.byref(Config())), 0)
        self.assertNotEqual(self.lib.yb_colour_validate(None), 0)
        self.assertNotEqual(self.lib.yb_colour_init(None, None), 0)
        self.assertNotEqual(self.lib.yb_colour_sample(C.byref(compiled), None, None), 0)

    def test_strided_chunk_all_stages_padding_and_largest_count(self):
        python = python_config()
        compiled = self.native_config(python)
        count = 65
        samples = [(i * 17 % 4096, i * 31 % 4096, i * 47 % 4096) for i in range(count)]
        input_array = (C.c_double * (count * 5))()
        for index, values in enumerate(samples):
            input_array[index * 5:index * 5 + 3] = values
            input_array[index * 5 + 3:index * 5 + 5] = (math.nan, math.inf)
        outputs = (Result * (count * 2))()
        C.memset(outputs, 0xA5, C.sizeof(outputs))
        padding = [bytes(outputs[i * 2 + 1]) for i in range(count)]
        self.assertEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), input_array, count, 5, outputs, 2), 0)
        for index, values in enumerate(samples):
            self.assert_result(outputs[index * 2], oracle.convert_sample(values, python))
            self.assertEqual(bytes(outputs[index * 2 + 1]), padding[index])
        large = 65536
        input_array = (C.c_double * (large * 3))(*([2048] * (large * 3)))
        outputs = (Result * large)()
        self.assertEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), input_array, large, 3, outputs, 1), 0)
        expected = oracle.convert_sample((2048, 2048, 2048), python)
        self.assertTrue(all(tuple(row.codes) == expected.codes for row in outputs))

    def test_chunk_late_domain_failure_no_partial_writes_alias_and_bounds(self):
        python = python_config(target_ycc=IDENTITY, target_offset=(0, 0, 0), target_lms=IDENTITY,
                               policy="reject-outside-unit", source_ycc=((2, 0, 0), (0, 1, 0), (0, 0, 1)))
        compiled = self.native_config(python)
        count = 9
        inputs = (C.c_double * (count * 3))(*([512] * (count * 3)))
        outputs = (Result * count)(); C.memset(outputs, 0xA5, C.sizeof(outputs))
        before = bytes(outputs)
        inputs[(count - 1) * 3] = 3000  # Valid u12 input, but late strict PQ excursion.
        self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), inputs, count, 3, outputs, 1), 0)
        self.assertEqual(bytes(outputs), before)
        inputs[(count - 1) * 3] = 512
        for size, input_stride, output_stride in ((0, 3, 1), (65537, 3, 1), (count, 2, 1),
                                                   (count, 65537, 1), (count, 3, 0), (count, 3, 65537)):
            self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), inputs, size,
                             input_stride, outputs, output_stride), 0)
            self.assertEqual(bytes(outputs), before)
        self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), inputs, 1, 3,
                         C.cast(inputs, C.POINTER(Result)), 1), 0)
        self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), inputs, 1, 3,
                         C.cast(C.byref(compiled), C.POINTER(Result)), 1), 0)
        backing = (C.c_ubyte * 256)()
        self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), inputs, 1, 3,
                         C.cast(C.byref(backing, 1), C.POINTER(Result)), 1), 0)
        overflow = C.cast(C.c_void_p((1 << (8 * C.sizeof(C.c_void_p))) - 8), C.POINTER(C.c_double))
        self.assertNotEqual(self.lib.yb_colour_process_chunk(C.byref(compiled), overflow, 1, 3, outputs, 1), 0)
        self.assertEqual(bytes(outputs), before)


if __name__ == "__main__":
    unittest.main()
