"""Synthetic diagnostic comparisons; Python is an oracle, never playback."""
import ctypes as C
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import reference
from nlq_scaling_sensitivity import formula_extension
from test_native_composer import NLQConfig


class Rational(C.Structure):
    _fields_ = [("uncapped_numerator", C.c_int64), ("capped_numerator", C.c_int64),
                ("divisor", C.c_uint64), ("floored_residual", C.c_int64)]


def metadata(config):
    return {name: getattr(config, name) for name in ("offset", "slope", "threshold", "maximum")}


class NativePrecisionProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise RuntimeError("GCC/Clang with signed __int128 required by native composer")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        here = Path(__file__).resolve().parent
        library = Path(cls.temporary.name) / "precision.so"
        subprocess.run([cc, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra",
                        "-Werror", "-Wconversion", "-Wshadow", str(here / "native_composer.c"),
                        str(here / "native_precision_probe.c"), "-o", str(library)],
                       check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.yb_probe_quantized.argtypes = [C.POINTER(NLQConfig), C.c_int64, C.c_int32,
                                              C.POINTER(C.c_int32), C.POINTER(C.c_int64)]
        cls.lib.yb_probe_literal.argtypes = [C.POINTER(NLQConfig), C.c_int64, C.POINTER(Rational)]
        cls.lib.yb_probe_quantized.restype = cls.lib.yb_probe_literal.restype = C.c_int

    def quantized(self, config, word, policy):
        sample, residual = C.c_int32(-123), C.c_int64(-456)
        status = self.lib.yb_probe_quantized(C.byref(config), word, policy,
                                             C.byref(sample), C.byref(residual))
        return status, sample.value, residual.value

    def literal(self, config, word):
        result = Rational(111, 222, 333, 444)
        status = self.lib.yb_probe_literal(C.byref(config), word, C.byref(result))
        return status, result

    def check_word(self, config, word):
        status, result = self.literal(config, word)
        self.assertEqual(status, 0)
        value = formula_extension(Fraction(word, 64), metadata(config), 10, config.denominator)
        self.assertEqual(Fraction(result.capped_numerator, result.divisor), value)
        self.assertEqual(result.floored_residual, value.numerator // value.denominator)
        delta = Fraction(word, 64) - config.offset
        sign = (delta > 0) - (delta < 0)
        uncap = ((2 * delta - sign) * config.slope + 2 * sign * config.threshold)
        uncap /= 1 << (config.denominator - 15)
        self.assertEqual(Fraction(result.uncapped_numerator, result.divisor), uncap)
        floor, remainder = divmod(word, 64)
        codes = [floor, floor + (remainder >= 32),
                 floor + (remainder > 32 or remainder == 32 and floor % 2 == 1)]
        for policy, code in enumerate(codes):
            expected = reference.inverse_el(code, metadata(config), 10, config.denominator)
            self.assertEqual(self.quantized(config, word, policy), (0, code, expected))

    @staticmethod
    def configs():
        for denominator in (15, 23, 32):
            bound = (2 << denominator) - 1
            for offset in (0, 1, 511, 512, 1023):
                for slope, threshold, maximum in ((2048, 0, 1024), (2048, 0, 1025),
                                                  (2048, 0, 1048576 if bound >= 1048576 else bound),
                                                  (bound, bound, bound), (0, 0, 0)):
                    yield NLQConfig(10, denominator, offset, slope, threshold, maximum)

    def test_every_integer_anchor_and_all_policies(self):
        # 75 configurations, 76800 native anchors; every candidate reduces
        # to the unchanged integer stage, including extreme coefficients.
        for config in self.configs():
            for code in range(1024):
                self.check_word(config, code * 64)

    def test_neutral_boundary_words_and_every_q6_word(self):
        distances = (0, 1, 16, 31, 32, 33, 63, 64, 65, 128)
        for config in self.configs():
            for distance in distances:
                for sign in (-1, 1):
                    word = config.offset * 64 + sign * distance
                    if 0 <= word <= 65472:
                        self.check_word(config, word)
        config = NLQConfig(10, 23, 512, 2048, 0, 1048576)
        for word in range(65473):
            self.check_word(config, word)

    def test_literal_discriminators_and_cap_before_floor(self):
        config = NLQConfig(10, 23, 512, 2048, 0, 1048576)
        for word, expected in ((32769, Fraction(-31, 4)), (32767, Fraction(31, 4)),
                               (32768, Fraction(0)), (32832, Fraction(8))):
            status, result = self.literal(config, word)
            self.assertEqual(status, 0)
            self.assertEqual(Fraction(result.capped_numerator, result.divisor), expected)
        self.assertEqual(self.quantized(config, 32767, 0), (0, 511, -8))
        self.assertEqual(self.quantized(config, 32767, 1), (0, 512, 0))
        self.assertEqual(self.quantized(config, 32800, 1), (0, 513, 8))
        self.assertEqual(self.quantized(config, 32800, 2), (0, 512, 0))
        config.maximum = 1025
        self.assertEqual(self.literal(config, 32896)[1].floored_residual, 8)
        self.assertEqual(self.literal(config, 32640)[1].floored_residual, -9)

    def test_rejection_preserves_outputs_no_overshoot_clamping(self):
        config = NLQConfig(10, 23, 512, 2048, 0, 1048576)
        for word in (-1, 65473, 65504, 65535, 2**63 - 1, -2**63):
            for policy in range(3):
                self.assertEqual(self.quantized(config, word, policy), (3, -123, -456))
            status, result = self.literal(config, word)
            self.assertEqual(status, 3)
            self.assertEqual(bytes(result), bytes(Rational(111, 222, 333, 444)))
        for policy in (-1, 3):
            self.assertEqual(self.quantized(config, 32768, policy), (1, -123, -456))
        for field, value in (("bit_depth", 8), ("denominator", 14), ("denominator", 33),
                             ("offset", -1), ("offset", 1024), ("slope", 2 << 23)):
            bad = NLQConfig(10, 23, 512, 2048, 0, 1048576)
            setattr(bad, field, value)
            self.assertEqual(self.literal(bad, 32768)[0], 2)
            self.assertEqual(self.quantized(bad, 32768, 0), (2, -123, -456))
        self.assertEqual(self.lib.yb_probe_literal(None, 32768, C.byref(Rational())), 1)
        self.assertEqual(self.lib.yb_probe_literal(C.byref(config), 32768, None), 1)


if __name__ == "__main__":
    unittest.main()
