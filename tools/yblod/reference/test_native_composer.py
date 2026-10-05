"""Build native scalar stages in a temporary directory; no GPU or playback."""
import copy
import ctypes as C
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

import reference


class Segment(C.Structure):
    _fields_ = [("method", C.c_int32), ("order", C.c_int32),
                ("constant", C.c_int64), ("coefficients", (C.c_int64 * 7) * 3)]


class Component(C.Structure):
    _fields_ = [("pivot_count", C.c_int32), ("pivots", C.c_int32 * 17),
                ("segments", Segment * 16)]


class MappingConfig(C.Structure):
    _fields_ = [("bit_depth", C.c_int32), ("denominator", C.c_int32),
                ("components", Component * 3)]


class NLQConfig(C.Structure):
    _fields_ = [("bit_depth", C.c_int32), ("denominator", C.c_int32),
                ("offset", C.c_int32), ("slope", C.c_uint64),
                ("threshold", C.c_uint64), ("maximum", C.c_uint64)]


def polynomial(pivots, coefficients):
    return {"pivots": pivots, "segments": [
        {"method": "polynomial", "coefficients": coefficients} for _ in pivots[1:]]}


def mmr(pivots, rows, constant=0):
    return {"pivots": pivots, "segments": [
        {"method": "mmr", "coefficients": rows, "constant": constant} for _ in pivots[1:]]}


def native_mapping(source, depth=10, denominator=23):
    # Test fixture adapter only: not a production manifest/RPU parser.
    config = MappingConfig(depth, denominator)
    for index, curve in enumerate(source):
        target = config.components[index]
        target.pivot_count = len(curve["pivots"])
        for i, pivot in enumerate(curve["pivots"]):
            target.pivots[i] = pivot
        for i, segment in enumerate(curve["segments"]):
            output = target.segments[i]
            output.method = 0 if segment["method"] == "polynomial" else 1
            output.order = len(segment["coefficients"]) - 1 if output.method == 0 else len(segment["coefficients"])
            if output.method == 0:
                for term, coefficient in enumerate(segment["coefficients"]):
                    output.coefficients[0][term] = coefficient
            else:
                output.constant = segment["constant"]
                for row, coefficients in enumerate(segment["coefficients"]):
                    for term, coefficient in enumerate(coefficients):
                        output.coefficients[row][term] = coefficient
    return config


class NativeComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise RuntimeError("native tests require a GCC/Clang C compiler with __int128")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        here = Path(__file__).resolve().parent
        library = Path(cls.temporary.name) / "libnative_composer.so"
        cls.compiler_version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
        subprocess.run([compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra",
                        "-Werror", "-Wconversion", "-Wshadow", str(here / "native_composer.c"),
                        "-o", str(library)], check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(library))
        for name, arguments in {
            "yb_validate_mapping": [C.POINTER(MappingConfig)],
            "yb_validate_nlq": [C.POINTER(NLQConfig)],
            "yb_map_sample": [C.POINTER(MappingConfig), C.c_int32, C.POINTER(C.c_int64), C.POINTER(C.c_uint16)],
            "yb_nlq": [C.POINTER(NLQConfig), C.c_int64, C.POINTER(C.c_int64)],
            "yb_compose_residual": [C.c_int64, C.c_int64, C.c_int32, C.POINTER(C.c_uint16)],
            "yb_compose": [C.POINTER(NLQConfig), C.c_int64, C.c_int64, C.c_int32, C.POINTER(C.c_uint16)],
            "yb_process_chunk": [C.POINTER(MappingConfig), C.POINTER(NLQConfig), C.c_int32,
                                  C.POINTER(C.c_uint16), C.POINTER(C.c_uint16), C.POINTER(C.c_uint16),
                                  C.POINTER(C.c_uint16), C.c_uint32, C.c_int32, C.c_int32,
                                  C.POINTER(C.c_uint16), C.POINTER(C.c_int32), C.POINTER(C.c_int32),
                                  C.POINTER(C.c_uint16)],
        }.items():
            function = getattr(cls.lib, name)
            function.argtypes, function.restype = arguments, C.c_int
        cls.lib.yb_abi_version.argtypes, cls.lib.yb_abi_version.restype = [], C.c_uint32
        for name in ("yb_sizeof_mapping_config", "yb_sizeof_nlq_config", "yb_sizeof_component_mapping", "yb_sizeof_segment"):
            getattr(cls.lib, name).argtypes, getattr(cls.lib, name).restype = [], C.c_uint64

    def map_value(self, config, component, values):
        output = C.c_uint16(12345)
        status = self.lib.yb_map_sample(C.byref(config), component, (C.c_int64 * 3)(*values), C.byref(output))
        self.assertEqual(status, 0)
        return output.value

    def nlq_value(self, config, sample):
        output = C.c_int64(12345)
        self.assertEqual(self.lib.yb_nlq(C.byref(config), sample, C.byref(output)), 0)
        return output.value

    def test_polynomial_all_native_codes_and_pivot_endpoints(self):
        count = 0
        for depth in (8, 10):
            last = (1 << depth) - 1
            for denominator in (13, 23, 32):
                unit = 1 << denominator
                for coefficients in ([0, unit], [127, 0], [128, 0], [0, 0, unit],
                                     [-unit, 2 * unit, -unit], [(64 << denominator) - 1, -(64 << denominator)]):
                    source = [polynomial([1, last // 2, last - 1], coefficients) for _ in range(3)]
                    config = native_mapping(source, depth, denominator)
                    self.assertEqual(self.lib.yb_validate_mapping(C.byref(config)), 0)
                    for sample in range(last + 1):
                        values = [sample, sample, sample]
                        for component in range(3):
                            self.assertEqual(self.map_value(config, component, values),
                                             reference.map_sample(component, values, source, depth, denominator))
                            count += 1
        self.assertEqual(count, 69120)

    def test_mmr_all_orders_signed_coefficients_and_wide_accumulators(self):
        random_source = random.Random(2296)
        count = 0
        for depth in (8, 10):
            last = (1 << depth) - 1
            for denominator in (13, 23, 32):
                unit, bound = 1 << denominator, 65536 << denominator
                for order in (1, 2, 3):
                    rows = [[unit // (i + 1) * (1 if j % 2 else -1) for j in range(7)]
                            for i in range(order)]
                    wide = [[bound - 1 if j % 2 else -bound for j in range(7)] for _ in range(order)]
                    source = [polynomial([3, last - 3], [0, unit]),
                              mmr([11, last - 7], rows, unit // 2),
                              mmr([17, last - 13], wide, -bound)]
                    config = native_mapping(source, depth, denominator)
                    for y in range(last + 1):
                        values = [y, (17 * y + 3) % (last + 1), (31 * y + 7) % (last + 1)]
                        for component in (1, 2):
                            self.assertEqual(self.map_value(config, component, values),
                                             reference.map_sample(component, values, source, depth, denominator))
                            count += 1
                    for _ in range(20):
                        values = [random_source.randrange(last + 1) for _ in range(3)]
                        self.assertEqual(self.map_value(config, 2, values),
                                         reference.map_sample(2, values, source, depth, denominator))
        self.assertEqual(count, 23040)

    def test_literal_mmr_truncations_per_channel_clamps_and_polynomials(self):
        unit = 1 << 23
        identity = polynomial([0, 1023], [0, unit])
        literals = [
            (mmr([0, 1023], [[0, 0, 0, unit, 0, 0, 0]]), [33, 17, 0], 35),
            (mmr([0, 1023], [[0, 0, 0, 0, 0, 0, 1 << 28]]), [33, 17, 9], 8),
            (mmr([0, 1023], [[0] * 7, [0, 0, 0, 1 << 32, 0, 0, 0]]), [200, 190, 0], 44064),
            (mmr([0, 1023], [[-unit, 0, 0, 0, 0, 0, 0]], unit // 2), [512, 0, 0], 0),
        ]
        for curve, values, expected in literals:
            self.assertEqual(self.map_value(native_mapping([identity, curve, identity]), 1, values), expected)
        y = polynomial([64, 960], [0, unit])
        u = mmr([16, 900], [[unit, 0, 0, 0, 0, 0, 0]])
        self.assertEqual(self.map_value(native_mapping([y, u, identity]), 1, [0, 17, 0]), 4096)
        piece = {"pivots": [0, 512, 1023], "segments": [
            {"method": "polynomial", "coefficients": [128, 0]},
            {"method": "polynomial", "coefficients": [256, 0]}]}
        config = native_mapping([piece, identity, identity])
        self.assertEqual([self.map_value(config, 0, [s, 0, 0]) for s in (511, 512, 1023)], [1, 2, 2])

    def test_nlq_all_codes_field_envelope_and_composition(self):
        count = 0
        for depth in (8, 10):
            for denominator in (depth + 5, 23, 32):
                bound = (2 << denominator) - 1
                for offset in (0, 1, 1 << (depth - 1), (1 << depth) - 1):
                    for slope, threshold, maximum in ((0, 0, 0), (0, 7, 5), (1, 0, 1),
                                                      (2048, 0, 1025), (3, 11, 17),
                                                      (bound, bound, bound), (bound, 0, 1)):
                        config = NLQConfig(depth, denominator, offset, slope, threshold, maximum)
                        parameters = dict(offset=offset, slope=slope, threshold=threshold, maximum=maximum)
                        self.assertEqual(self.lib.yb_validate_nlq(C.byref(config)), 0)
                        for sample in range(1 << depth):
                            expected = reference.inverse_el(sample, parameters, depth, denominator)
                            self.assertEqual(self.nlq_value(config, sample), expected)
                            for output_depth in (10, 12):
                                output = C.c_uint16()
                                self.assertEqual(self.lib.yb_compose(C.byref(config), 32768, sample,
                                                                  output_depth, C.byref(output)), 0)
                                self.assertEqual(output.value, reference.reconstruct(32768, expected, output_depth))
                            count += 1
        self.assertEqual(count, 107520)

    def test_literal_cap_floor_and_output_ties_extreme_signed_sums(self):
        config = NLQConfig(10, 23, 512, 2048, 0, 1025)
        self.assertEqual([self.nlq_value(config, s) for s in (510, 511, 512, 513, 514)], [-9, -8, 0, 8, 8])
        config = NLQConfig(8, 13, 128, 3, 1, 5)
        self.assertEqual([self.nlq_value(config, s) for s in (128, 129, 130, 127, 126)], [0, 20, 40, -20, -40])
        for depth, cases in {
            12: [(0, 7, 0), (0, 8, 1), (16, -8, 1), (16, -9, 0), (65520, -9, 4094)],
            10: [(0, 31, 0), (0, 32, 1), (64, -32, 1), (64, -33, 0), (65472, -33, 1022)],
        }.items():
            for mapped, residual, expected in cases:
                output = C.c_uint16()
                self.assertEqual(self.lib.yb_compose_residual(mapped, residual, depth, C.byref(output)), 0)
                self.assertEqual(output.value, expected)
            for mapped in (0, 1, 32768, 65535):
                for residual in (-(1 << 63), (1 << 63) - 1, -131072, -65536, -1, 0, 1, 131071):
                    output = C.c_uint16()
                    self.assertEqual(self.lib.yb_compose_residual(mapped, residual, depth, C.byref(output)), 0)
                    self.assertEqual(output.value, reference.reconstruct(mapped, residual, depth))

    def test_strict_native_metadata_samples_and_unchanged_failed_outputs(self):
        source = [polynomial([0, 1023], [0, 1 << 23]) for _ in range(3)]
        original = native_mapping(source)
        invalid = []
        for field, value in (("bit_depth", 9), ("denominator", 12), ("denominator", 33)):
            config = copy.deepcopy(original); setattr(config, field, value); invalid.append(config)
        for mutate in (
            lambda c: setattr(c.components[0], "pivot_count", 1),
            lambda c: setattr(c.components[0], "pivot_count", 18),
            lambda c: c.components[0].pivots.__setitem__(1, 0),
            lambda c: c.components[0].pivots.__setitem__(1, 1024),
            lambda c: c.components[0].pivots.__setitem__(2, 1),
            lambda c: setattr(c.components[0].segments[0], "constant", 1),
            lambda c: setattr(c.components[0].segments[0], "method", 2),
            lambda c: setattr(c.components[0].segments[0], "order", 0),
            lambda c: c.components[0].segments[0].coefficients[0].__setitem__(0, 64 << 23),
            lambda c: c.components[0].segments[0].coefficients[1].__setitem__(0, 1),
            lambda c: setattr(c.components[0].segments[1], "order", 1),
        ):
            config = copy.deepcopy(original); mutate(config); invalid.append(config)
        for config in invalid:
            output = C.c_uint16(12345)
            self.assertNotEqual(self.lib.yb_validate_mapping(C.byref(config)), 0)
            self.assertNotEqual(self.lib.yb_map_sample(C.byref(config), 0, (C.c_int64 * 3)(0, 0, 0), C.byref(output)), 0)
            self.assertEqual(output.value, 12345)
        for component, values in ((-1, [0, 0, 0]), (3, [0, 0, 0]),
                                  (0, [-1, 0, 0]), (0, [0, 1024, 0])):
            output = C.c_uint16(12345)
            self.assertNotEqual(self.lib.yb_map_sample(C.byref(original), component, (C.c_int64 * 3)(*values), C.byref(output)), 0)
            self.assertEqual(output.value, 12345)
        good = NLQConfig(10, 23, 512, 2048, 0, 1024)
        for field, value in (("bit_depth", 9), ("denominator", 14), ("denominator", 33),
                             ("offset", -1), ("offset", 1024), ("slope", 1 << 24),
                             ("threshold", 1 << 24), ("maximum", (1 << 64) - 1)):
            config = copy.deepcopy(good); setattr(config, field, value)
            output = C.c_int64(12345)
            self.assertNotEqual(self.lib.yb_nlq(C.byref(config), 512, C.byref(output)), 0)
            self.assertEqual(output.value, 12345)
        for sample in (-1, 1024, -(1 << 63), (1 << 63) - 1):
            output = C.c_int64(12345)
            self.assertNotEqual(self.lib.yb_nlq(C.byref(good), sample, C.byref(output)), 0)
            self.assertEqual(output.value, 12345)
        for mapped, depth in ((-1, 12), (65536, 12), (0, 8), (0, 16)):
            output = C.c_uint16(12345)
            self.assertNotEqual(self.lib.yb_compose_residual(mapped, 0, depth, C.byref(output)), 0)
            self.assertEqual(output.value, 12345)
        self.assertNotEqual(self.lib.yb_validate_mapping(None), 0)
        self.assertNotEqual(self.lib.yb_validate_nlq(None), 0)
        self.assertNotEqual(self.lib.yb_map_sample(C.byref(original), 0, None, None), 0)
        self.assertNotEqual(self.lib.yb_nlq(C.byref(good), 512, None), 0)
        self.assertNotEqual(self.lib.yb_compose_residual(0, 0, 12, None), 0)
        self.assertNotEqual(self.lib.yb_compose(C.byref(good), 0, 512, 12, None), 0)

    def test_abi_and_chunk_all_stages_mixed_depths_and_mmr_orders(self):
        self.assertEqual(self.lib.yb_abi_version(), 1)
        for name, structure in (("mapping_config", MappingConfig), ("nlq_config", NLQConfig),
                                ("component_mapping", Component), ("segment", Segment)):
            self.assertEqual(getattr(self.lib, "yb_sizeof_" + name)(), C.sizeof(structure))
        for base_depth in (8, 10):
            last = (1 << base_depth) - 1
            for enhancement_depth in (8, 10):
                center = 1 << (enhancement_depth - 1)
                parameters = dict(offset=center, slope=2048, threshold=0, maximum=1025)
                nlq = NLQConfig(enhancement_depth, 23, **parameters)
                for order in (1, 2, 3):
                    unit = 1 << 23
                    rows = [[unit // (i + 1) * (1 if j % 2 else -1) for j in range(7)]
                            for i in range(order)]
                    source = [polynomial([3, last - 3], [0, unit]),
                              mmr([11, last - 7], rows, unit // 2),
                              mmr([17, last - 13], rows, -unit // 3)]
                    config = native_mapping(source, base_depth, 23)
                    count = 257
                    values = [[(i * factor + 3) % (last + 1) for i in range(count)] for factor in (13, 17, 31)]
                    enhancement = [(i * 7 + 1) % (1 << enhancement_depth) for i in range(count)]
                    arrays = [(C.c_uint16 * count)(*row) for row in values]
                    el = (C.c_uint16 * count)(*enhancement)
                    for component in (0, 1, 2):
                        for depth in (10, 12):
                            outputs = [(kind * count)() for kind in (C.c_uint16, C.c_int32, C.c_int32, C.c_uint16)]
                            self.assertEqual(self.lib.yb_process_chunk(C.byref(config), C.byref(nlq), component,
                                             *arrays, el, count, 1, depth, *outputs), 0)
                            for i in range(count):
                                triplet = [row[i] for row in values]
                                mapped = reference.map_sample(component, triplet, source, base_depth, 23)
                                residual = reference.inverse_el(enhancement[i], parameters, enhancement_depth, 23)
                                self.assertEqual([o[i] for o in outputs],
                                                 [mapped, residual, mapped + residual, reference.reconstruct(mapped, residual, depth)])

    def test_chunk_base_only_largest_count_and_no_intermediate_cap(self):
        unit = 1 << 32
        source = [polynomial([0, 1023], [0, unit]) for _ in range(3)]
        config = native_mapping(source, 10, 32)
        count = 65536
        y = (C.c_uint16 * count)(*([513] * count))
        zero = (C.c_uint16 * count)()
        outputs = [(kind * count)() for kind in (C.c_uint16, C.c_int32, C.c_int32, C.c_uint16)]
        self.assertEqual(self.lib.yb_process_chunk(C.byref(config), None, 0, y, zero, zero,
                         None, count, 0, 12, *outputs), 0)
        self.assertTrue(all(v == 32832 for v in outputs[0]))
        self.assertTrue(all(v == 0 for v in outputs[1]))
        self.assertTrue(all(v == 32832 for v in outputs[2]))
        self.assertTrue(all(v == 2052 for v in outputs[3]))
        nlq = NLQConfig(10, 32, 512, (2 << 32) - 1, 0, (2 << 32) - 1)
        el = (C.c_uint16 * 2)(510, 514)
        small_y = (C.c_uint16 * 2)(1023, 1023)
        small_zero = (C.c_uint16 * 2)()
        outputs = [(kind * 2)() for kind in (C.c_uint16, C.c_int32, C.c_int32, C.c_uint16)]
        self.assertEqual(self.lib.yb_process_chunk(C.byref(config), C.byref(nlq), 0, small_y,
                         small_zero, small_zero, el, 2, 1, 12, *outputs), 0)
        self.assertEqual(list(outputs[1]), [-131072, 131071])
        self.assertEqual(list(outputs[2]), [-65600, 196543])
        self.assertEqual(list(outputs[3]), [0, 4095])

    def test_chunk_preflight_invalid_late_sample_metadata_and_explicit_disable(self):
        config = native_mapping([polynomial([0, 1023], [0, 1 << 23]) for _ in range(3)])
        nlq = NLQConfig(10, 23, 512, 2048, 0, 1025)
        arrays = [(C.c_uint16 * 3)(512, 513, 511) for _ in range(4)]
        outputs = [(kind * 3)(*([12345] * 3)) for kind in (C.c_uint16, C.c_int32, C.c_int32, C.c_uint16)]
        def rejected(*args):
            self.assertNotEqual(self.lib.yb_process_chunk(*args), 0)
            self.assertTrue(all(list(o) == [12345] * 3 for o in outputs))
        for index in range(4):
            arrays[index][2] = 1024
            rejected(C.byref(config), C.byref(nlq), 0, *arrays, 3, 1, 12, *outputs)
            arrays[index][2] = 511
        for count, enabled, component, depth in ((0, 1, 0, 12), (65537, 1, 0, 12),
                                                (3, -1, 0, 12), (3, 2, 0, 12),
                                                (3, 1, -1, 12), (3, 1, 3, 12), (3, 1, 0, 16)):
            rejected(C.byref(config), C.byref(nlq), component, *arrays, count, enabled, depth, *outputs)
        rejected(C.byref(config), C.byref(nlq), 0, *arrays, 3, 0, 12, *outputs)
        rejected(C.byref(config), None, 0, *arrays, 3, 0, 12, *outputs)
        rejected(C.byref(config), C.byref(nlq), 0, *arrays[:3], None, 3, 1, 12, *outputs)
        rejected(None, C.byref(nlq), 0, *arrays, 3, 1, 12, *outputs)
        altered = copy.deepcopy(nlq); altered.denominator = 20
        rejected(C.byref(config), C.byref(altered), 0, *arrays, 3, 1, 12, *outputs)
        altered_map = copy.deepcopy(config); altered_map.components[2].segments[0].order = 0
        rejected(C.byref(altered_map), C.byref(nlq), 0, *arrays, 3, 1, 12, *outputs)

    def test_chunk_rejects_output_alias_alignment_and_address_overflow(self):
        config = native_mapping([polynomial([0, 1023], [0, 1 << 23]) for _ in range(3)])
        arrays = [(C.c_uint16 * 2)(512, 513) for _ in range(3)]
        outputs = [(kind * 2)(12345, 12345) for kind in (C.c_uint16, C.c_int32, C.c_int32, C.c_uint16)]
        def rejected(input_y=arrays[0], mapped=outputs[0], residual=outputs[1], summed=outputs[2], reconstructed=outputs[3]):
            self.assertNotEqual(self.lib.yb_process_chunk(C.byref(config), None, 0,
                             input_y, arrays[1], arrays[2], None, 2, 0, 12,
                             mapped, residual, summed, reconstructed), 0)
            self.assertTrue(all(list(o) == [12345, 12345] for o in outputs))
        rejected(mapped=arrays[0])
        self.assertEqual(list(arrays[0]), [512, 513])
        rejected(reconstructed=outputs[0])
        rejected(summed=outputs[1])
        rejected(mapped=C.cast(C.byref(config), C.POINTER(C.c_uint16)))
        backing = (C.c_ubyte * 16)()
        rejected(mapped=C.cast(C.byref(backing, 1), C.POINTER(C.c_uint16)))
        rejected(residual=C.cast(C.byref(backing, 2), C.POINTER(C.c_int32)))
        rejected(input_y=C.cast(C.c_void_p((1 << (8 * C.sizeof(C.c_void_p))) - 2), C.POINTER(C.c_uint16)))


if __name__ == "__main__":
    unittest.main()
