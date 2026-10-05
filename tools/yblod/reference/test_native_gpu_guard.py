"""Host-only width proof tests; never create a GPU context or shader."""
import ctypes as C
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from test_native_composer import MappingConfig, native_mapping, polynomial


LIMIT = (2**63 - 1) // 2**20


class Report(C.Structure):
    _fields_ = [("supported", C.c_uint32), ("mmr_segment_count", C.c_uint32),
                ("worst_l1_bound", C.c_uint64),
                ("first_unsupported_component", C.c_int32),
                ("first_unsupported_segment", C.c_int32)]


def baseline(denominator=23, depth=10):
    return native_mapping([polynomial([0, (1 << depth)-1], [0, 1 << denominator])
                           for _ in range(3)], depth, denominator)


def assign_l1(segment, total, denominator, order=3, negative=False):
    segment.method, segment.order = 1, order
    segment.constant = 0
    for row in range(3):
        for term in range(7):
            segment.coefficients[row][term] = 0
    # Positive maximum is one below magnitude of permitted negative minimum.
    maximum = (65536 << denominator) - (not negative)
    fields = [min(total, maximum)]
    total -= fields[0]
    for _ in range(order * 7):
        fields.append(min(total, maximum))
        total -= fields[-1]
    if total:
        raise ValueError("requested L1 cannot fit declared segment metadata")
    sign = -1 if negative else 1
    segment.constant = sign * fields[0]
    for i, value in enumerate(fields[1:]):
        segment.coefficients[i//7][i%7] = sign * value


def oracle(config):
    bounds, first = [], (-1, -1)
    for component, curve in enumerate(config.components):
        for index in range(curve.pivot_count - 1):
            segment = curve.segments[index]
            if segment.method != 1:
                continue
            bound = abs(segment.constant) + sum(abs(segment.coefficients[row][term])
                for row in range(segment.order) for term in range(7))
            bounds.append(bound)
            if bound > LIMIT and first == (-1, -1):
                first = component, index
    return (int(first == (-1, -1)), len(bounds), max(bounds, default=0), *first)


class NativeGPUWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise RuntimeError("GCC/Clang signed __int128 composer compiler required")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        here = Path(__file__).resolve().parent
        library = Path(cls.temporary.name) / "guard.so"
        subprocess.run([cc, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra",
                        "-Werror", "-Wconversion", "-Wshadow", str(here / "native_gpu_guard.c"),
                        str(here / "native_composer.c"), "-o", str(library)],
                       check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.yb_gpu_check_mapping_width.argtypes = [C.POINTER(MappingConfig), C.POINTER(Report)]
        cls.lib.yb_gpu_check_mapping_width.restype = C.c_int
        cls.lib.yb_sizeof_gpu_width_report.restype = C.c_uint64
        cls.lib.yb_map_sample.argtypes = [C.POINTER(MappingConfig), C.c_int32,
                                         C.POINTER(C.c_int64), C.POINTER(C.c_uint16)]
        cls.lib.yb_map_sample.restype = C.c_int

    def check(self, config):
        report = Report(99, 98, 97, 96, 95)
        self.assertEqual(self.lib.yb_gpu_check_mapping_width(C.byref(config), C.byref(report)), 0)
        actual = tuple(getattr(report, name) for name, _ in Report._fields_)
        self.assertEqual(actual, oracle(config))
        return actual

    def test_polynomial_and_l1_threshold_neighbours(self):
        self.assertEqual(self.lib.yb_sizeof_gpu_width_report(), C.sizeof(Report))
        for denominator in (13, 23, 32):
            for depth in (8, 10):
                self.assertEqual(self.check(baseline(denominator, depth)), (1, 0, 0, -1, -1))
                capacity = 22 * ((65536 << denominator)-1)
                for negative in (False, True):
                    for bound in (0, 1, min(capacity, LIMIT-1), min(capacity, LIMIT),
                                  min(capacity, LIMIT+1), capacity):
                        config = baseline(denominator, depth)
                        assign_l1(config.components[1].segments[0], bound, denominator,
                                  negative=negative)
                        answer = self.check(config)
                        self.assertEqual(answer[0], int(bound <= LIMIT))
                if denominator >= 23:
                    for bound in range(LIMIT-32, LIMIT+33):
                        config = baseline(denominator, depth)
                        assign_l1(config.components[1].segments[0], bound, denominator)
                        self.check(config)

    def test_all_segments_count_and_first_rejection_not_worst(self):
        config = native_mapping([polynomial([0, 300, 700, 1023], [0, 1 << 32])
                                 for _ in range(3)], 10, 32)
        for component in (1, 2):
            for index, bound in enumerate((1, LIMIT+1, LIMIT+99)):
                assign_l1(config.components[component].segments[index], bound, 32)
        self.assertEqual(self.check(config), (0, 6, LIMIT+99, 1, 1))

    def test_random_valid_metadata_and_every_prefix_bound(self):
        rng = random.Random(719)
        for denominator in (13, 23, 32):
            maximum = 65536 << denominator
            for _ in range(240):
                config = baseline(denominator, rng.choice((8, 10)))
                segment = config.components[1].segments[0]
                segment.method, segment.order = 1, rng.randint(1, 3)
                segment.constant = rng.randrange(-maximum, maximum)
                for row in range(3):
                    for term in range(7):
                        segment.coefficients[row][term] = (
                            rng.randrange(-maximum, maximum) if row < segment.order else 0)
                self.check(config)
                coefficients = [segment.constant] + [segment.coefficients[row][term]
                    for row in range(segment.order) for term in range(7)]
                bound = sum(map(abs, coefficients)) * 2**20
                # Worst-prefix triangle bound includes the constant multiplier.
                # Actual feature values are <=2^20, so arbitrary endpoints here
                # cover a strictly larger domain than real correlated features.
                for direction in (-1, 1):
                    prefix = 0
                    for coefficient in coefficients:
                        feature = 2**20 if coefficient * direction > 0 else 0
                        prefix += coefficient * feature
                        self.assertLessEqual(abs(prefix), bound)
                        if bound <= 2**63-1:
                            self.assertTrue(-2**63 <= prefix <= 2**63-1)

    def test_guard_rejection_is_not_cpu_metadata_rejection(self):
        for negative in (False, True):
            config = baseline(32)
            assign_l1(config.components[1].segments[0], LIMIT+1, 32, negative=negative)
            self.assertEqual(self.check(config)[0], 0)
            for codes in ((0, 0, 0), (1023, 1023, 1023), (1023, 1, 511)):
                output = C.c_uint16(123)
                self.assertEqual(self.lib.yb_map_sample(C.byref(config), 1,
                                 (C.c_int64*3)(*codes), C.byref(output)), 0)
                self.assertEqual(output.value, 0 if negative else 65535)

    def test_feature_generation_products_before_each_floor(self):
        rng = random.Random(12309)
        for depth in (8, 10):
            maximum = (1 << depth)-1
            cases = [(a, b, c) for a in (0, 1, maximum) for b in (0, 1, maximum)
                     for c in (0, 1, maximum)]
            cases.extend(tuple(rng.randint(0, maximum) for _ in range(3)) for _ in range(4000))
            for codes in cases:
                linear = [code << (20-depth) for code in codes]
                squared = [code*code << (20-2*depth) for code in codes]
                linear.extend(codes[a]*codes[b] << (20-2*depth)
                              for a, b in ((0, 1), (0, 2), (1, 2)))
                product = linear[3]*linear[2]
                self.assertLess(product, 2**40)
                linear.append(product // 2**20)
                for term in linear[3:]:
                    self.assertLess(term*term, 2**40)
                    squared.append(term*term // 2**20)
                cubed = []
                for a, b in zip(linear, squared):
                    self.assertLess(a*b, 2**40)
                    cubed.append(a*b // 2**20)
                self.assertTrue(all(0 <= term < 2**20 for row in (linear, squared, cubed) for term in row))

    def test_invalid_metadata_and_null_preserve_report(self):
        for mutate in (
            lambda c: setattr(c, "denominator", 33),
            lambda c: setattr(c, "bit_depth", 12),
            lambda c: setattr(c.components[1], "pivot_count", 1),
            lambda c: setattr(c.components[1].segments[0], "constant", -2**63),
            lambda c: setattr(c.components[1].segments[1], "order", 1),
        ):
            config = baseline()
            mutate(config)
            report = Report(99, 98, 97, 96, 95)
            before = bytes(report)
            self.assertEqual(self.lib.yb_gpu_check_mapping_width(C.byref(config), C.byref(report)), 2)
            self.assertEqual(bytes(report), before)
        report = Report(99, 98, 97, 96, 95)
        self.assertEqual(self.lib.yb_gpu_check_mapping_width(None, C.byref(report)), 1)
        self.assertEqual(self.lib.yb_gpu_check_mapping_width(C.byref(baseline()), None), 1)


if __name__ == "__main__":
    unittest.main()
