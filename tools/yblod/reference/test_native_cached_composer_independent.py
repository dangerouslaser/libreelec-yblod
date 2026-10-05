"""Independent synthetic cached-backend checks against unchanged C/Python.

No movie fixtures, fractional policy or performance claims. Implementation
ownership remains separate; these tests do not build lookup tables themselves.
"""
import ctypes as C
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest
import reference
import native_integration_frame as frame
from test_native_composer import MappingConfig, NLQConfig, native_mapping, polynomial, mmr

ROOT = Path(__file__).resolve().parent


class CachedIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name) / "cached.so"
        subprocess.run(["cc", "-std=c11", "-O2", "-fPIC", "-shared", "-Wall",
            "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            *shlex.split(os.environ.get("YB_CACHED_TEST_CFLAGS", "")),
            *(str(ROOT / name) for name in ("native_cached_composer.c", "native_composer.c",
              "native_integration_probe.c", "native_sampling_probe.c")),
            "-o", str(path)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(path))
        u16, i32 = C.POINTER(C.c_uint16), C.POINTER(C.c_int32)
        cls.lib.yb_cached_create.argtypes = [C.POINTER(MappingConfig), C.POINTER(NLQConfig),
                                            C.c_int32, C.c_int32, C.POINTER(C.c_void_p)]
        cls.lib.yb_cached_create.restype = C.c_int
        cls.lib.yb_cached_destroy.argtypes = [C.c_void_p]
        cls.lib.yb_cached_destroy.restype = None
        cls.lib.yb_cached_component_route.argtypes = [C.c_void_p, C.c_int32]
        cls.lib.yb_cached_component_route.restype = C.c_int
        cls.lib.yb_cached_process_chunk.argtypes = [C.c_void_p, C.c_int32,
            u16, u16, u16, u16, C.c_uint32, u16, i32, i32, u16]
        cls.lib.yb_cached_process_chunk.restype = C.c_int
        cls.lib.yb_process_chunk.argtypes = [C.POINTER(MappingConfig), C.POINTER(NLQConfig),
            C.c_int32, u16, u16, u16, u16, C.c_uint32, C.c_int32, C.c_int32, u16, i32, i32, u16]
        cls.lib.yb_process_chunk.restype = C.c_int
        cls.lib.yb_cached_frame_create.argtypes = [C.POINTER(frame.Descriptor),
            C.POINTER(MappingConfig), C.POINTER(NLQConfig), C.POINTER(C.c_void_p)]
        cls.lib.yb_cached_frame_create.restype = C.c_int
        cls.lib.yb_cached_frame_destroy.argtypes = [C.c_void_p]
        cls.lib.yb_cached_frame_destroy.restype = None
        cls.lib.yb_cached_frame_process.argtypes = [C.c_void_p, C.POINTER(C.c_uint8),
            C.c_int32, C.c_uint64, u16, u16, u16, u16, C.c_uint32, u16, i32, i32, u16]
        cls.lib.yb_cached_frame_process.restype = C.c_int
        cls.lib.yb_cached_frame_finish.argtypes = [C.c_void_p, C.POINTER(frame.Completion)]
        cls.lib.yb_cached_frame_finish.restype = C.c_int

    def plan(self, mapping, nlq, enabled=1, output=12):
        pointer = C.c_void_p()
        self.assertEqual(self.lib.yb_cached_create(C.byref(mapping), nlq, enabled,
                                                  output, C.byref(pointer)), 0)
        self.assertTrue(pointer.value)
        self.addCleanup(self.lib.yb_cached_destroy, pointer)
        return pointer

    def stages(self, n):
        return ((C.c_uint16 * n)(*([12345] * n)), (C.c_int32 * n)(*([12345] * n)),
                (C.c_int32 * n)(*([12345] * n)), (C.c_uint16 * n)(*([12345] * n)))

    def compare(self, source, depth, denominator, parameters, output, triples, el_codes, enabled=1, el_depth=None):
        el_depth = depth if el_depth is None else el_depth
        mapping = native_mapping(source, depth, denominator)
        nlq = (NLQConfig * 3)(*(NLQConfig(el_depth, denominator, **p) for p in parameters)) if enabled else None
        pointer = self.plan(mapping, nlq, enabled, output)
        n = len(triples)
        arrays = [(C.c_uint16 * n)(*(t[c] for t in triples)) for c in range(3)]
        el = (C.c_uint16 * n)(*el_codes) if enabled else None
        for component in range(3):
            actual, old = self.stages(n), self.stages(n)
            self.assertEqual(self.lib.yb_cached_process_chunk(pointer, component, *arrays, el, n, *actual), 0)
            selected_nlq = C.cast(C.byref(nlq, component * C.sizeof(NLQConfig)), C.POINTER(NLQConfig)) if enabled else None
            self.assertEqual(self.lib.yb_process_chunk(C.byref(mapping), selected_nlq, component,
                *arrays, el, n, enabled, output, *old), 0)
            self.assertEqual([list(v) for v in actual], [list(v) for v in old])
            expected = [[], [], [], []]
            for i, triple in enumerate(triples):
                mapped = reference.map_sample(component, triple, source, depth, denominator)
                residual = reference.inverse_el(el_codes[i], parameters[component], el_depth, denominator) if enabled else 0
                values = (mapped, residual, mapped + residual, reference.reconstruct(mapped, residual, output))
                for stage, value in zip(expected, values): stage.append(value)
            self.assertEqual([list(v) for v in actual], expected)
        return pointer, mapping, nlq

    def test_public_abi_size_and_invalid_route_queries(self):
        self.lib.yb_cached_abi_version.argtypes = []
        self.lib.yb_cached_abi_version.restype = C.c_uint32
        self.assertEqual(self.lib.yb_cached_abi_version(), 1)
        for name in ("yb_cached_sizeof_plan", "yb_cached_sizeof_frame"):
            query = getattr(self.lib, name); query.argtypes = []; query.restype = C.c_uint64
            self.assertGreater(query(), 0)
            self.assertLessEqual(query(), 128 * 1024)
        self.assertEqual(self.lib.yb_cached_component_route(None, 0), -1)
        _, mapping, nlq = self.fixture(); plan = self.plan(mapping, nlq)
        for component in (-1, 3):
            self.assertEqual(self.lib.yb_cached_component_route(plan, component), -1)

    def test_extreme_nlq_limits_and_mixed_base_enhancement_depths(self):
        for depth in (8, 10):
            last = (1 << depth) - 1
            for denominator in (depth + 5, 23, 32):
                unit = 1 << denominator; bound = (1 << (denominator + 1)) - 1
                source = [polynomial([0, last], [0, unit])] * 3
                triples = [(i, last - i, i) for i in range(last + 1)]
                parameters = [dict(offset=0, slope=bound, threshold=bound, maximum=bound),
                    dict(offset=last, slope=bound, threshold=bound, maximum=bound),
                    dict(offset=last // 2, slope=bound, threshold=0, maximum=bound)]
                for output in (10, 12):
                    self.compare(source, depth, denominator, parameters, output,
                                 triples, list(range(last + 1)))
        source = [polynomial([0, 1023], [0, 1 << 23])] * 3
        parameters = [dict(offset=128, slope=2048, threshold=11, maximum=1025)] * 3
        _, mapping, nlq = self.compare(source, 10, 23, parameters, 12,
            [(i * 4, 1023 - i * 4, i * 4) for i in range(256)], list(range(256)), el_depth=8)
        descriptor = frame.Descriptor(1, 1, 2, 2, 12, 1)
        handle = C.c_void_p(); token = (C.c_uint8 * 32)()
        self.assertEqual(self.lib.yb_cached_frame_create(C.byref(descriptor),
            C.byref(mapping), nlq, C.byref(handle)), 0)
        self.addCleanup(self.lib.yb_cached_frame_destroy, handle)
        bl = (C.c_uint16 * 4)(512, 513, 511, 514)
        el = (C.c_uint16 * 4)(128, 129, 127, 130)
        for component, count in enumerate((4, 1, 1)):
            actual, old = self.stages(count), self.stages(count)
            self.assertEqual(self.lib.yb_cached_frame_process(handle, token, component,
                0, bl, bl, bl, el, count, *actual), 0)
            selected = C.cast(C.byref(nlq, component * C.sizeof(NLQConfig)), C.POINTER(NLQConfig))
            self.assertEqual(self.lib.yb_process_chunk(C.byref(mapping), selected,
                component, bl, bl, bl, el, count, 1, 12, *old), 0)
            self.assertEqual([bytes(v) for v in actual], [bytes(v) for v in old])
        completion = frame.Completion()
        self.assertEqual(self.lib.yb_cached_frame_finish(handle, C.byref(completion)), 0)
        self.assertEqual(list(completion.counts), [4, 1, 1])

    def test_exhaustive_native_domains_pivots_caps_and_output_rounding(self):
        for depth in (8, 10):
            last = (1 << depth) - 1
            triples = [(i, (i * 17 + 3) & last, (i * 31 + 7) & last) for i in range(last + 1)]
            for denominator in (depth + 5, 23, 32):
                unit = 1 << denominator
                piece = {"pivots": [1, last // 2, last - 1], "segments": [
                    {"method": "polynomial", "coefficients": [128, unit, -unit]},
                    {"method": "polynomial", "coefficients": [-256, unit]}]}
                source = [piece, polynomial([0, last], [-unit, 2 * unit]),
                          polynomial([3, last - 3], [0, 0, unit])]
                for output in (10, 12):
                    parameters = [dict(offset=last // 2, slope=3, threshold=11, maximum=17),
                        dict(offset=0, slope=(2 << denominator) - 1, threshold=0, maximum=1),
                        dict(offset=last, slope=2048, threshold=7, maximum=1025)]
                    pointer, _, _ = self.compare(source, depth, denominator, parameters,
                        output, triples, list(range(last + 1)))
                    self.assertEqual([self.lib.yb_cached_component_route(pointer, c) for c in range(3)], [1, 1, 1])

    def test_seeded_mmr_fallback_and_mixed_component_routes(self):
        rng = random.Random(2296)
        for depth in (8, 10):
            last = (1 << depth) - 1; unit = 1 << 23
            for order in (1, 2, 3):
                rows = [[unit // (r + 1) * (-1 if c % 2 else 1) for c in range(7)] for r in range(order)]
                source = [polynomial([0, last], [0, unit]), mmr([1, last - 1], rows, -unit),
                          mmr([0, last], rows, unit // 2)]
                parameters = [dict(offset=last // 2, slope=2048, threshold=3, maximum=1025)] * 3
                triples = [tuple(rng.randrange(last + 1) for _ in range(3)) for _ in range(257)]
                pointer, _, _ = self.compare(source, depth, 23, parameters, 12,
                    triples, [rng.randrange(last + 1) for _ in triples])
                self.assertEqual([self.lib.yb_cached_component_route(pointer, c) for c in range(3)], [1, 0, 0])

    def fixture(self):
        source = [polynomial([0, 1023], [0, 1 << 23])] * 3
        mapping = native_mapping(source)
        nlq = (NLQConfig * 3)(*(NLQConfig(10, 23, 512, 2048, 0, 1025) for _ in range(3)))
        return source, mapping, nlq

    def test_owned_copy_and_replacement_plan_are_isolated(self):
        _, mapping, nlq = self.fixture()
        first = self.plan(mapping, nlq)
        inputs = (C.c_uint16 * 2)(512, 513)
        original = self.stages(2)
        self.assertEqual(self.lib.yb_cached_process_chunk(first, 0, inputs, inputs, inputs, inputs, 2, *original), 0)
        mapping.components[0].segments[0].coefficients[0][1] = 0
        nlq[0].maximum = 0
        second = self.plan(mapping, nlq)
        later, replacement = self.stages(2), self.stages(2)
        self.assertEqual(self.lib.yb_cached_process_chunk(first, 0, inputs, inputs, inputs, inputs, 2, *later), 0)
        self.assertEqual(self.lib.yb_cached_process_chunk(second, 0, inputs, inputs, inputs, inputs, 2, *replacement), 0)
        self.assertEqual([list(v) for v in original], [list(v) for v in later])
        self.assertNotEqual([list(v) for v in later], [list(v) for v in replacement])

    def test_disabled_enhancement_is_explicit(self):
        source, _, _ = self.fixture()
        self.compare(source, 10, 23, [], 10, [(0, 1, 2), (1023, 511, 512)], [], enabled=0)
        _, mapping, nlq = self.fixture(); sentinel = C.c_void_p(12345)
        self.assertNotEqual(self.lib.yb_cached_create(C.byref(mapping), nlq, 0, 12, C.byref(sentinel)), 0)
        self.assertEqual(sentinel.value, 12345)
        self.lib.yb_cached_destroy(None)

    def test_invalid_late_codes_null_count_and_alias_preserve_outputs(self):
        _, mapping, nlq = self.fixture(); pointer = self.plan(mapping, nlq)
        for fault in ("late_y", "late_cb", "late_cr", "late_el", "null", "zero", "large", "alias", "component"):
            arrays = [(C.c_uint16 * 2)(512, 513) for _ in range(4)]
            stages = self.stages(2); count = 2; component = 0
            if fault.startswith("late_"): arrays[("y", "cb", "cr", "el").index(fault[5:])][1] = 1024
            elif fault == "null": arrays[0] = None
            elif fault == "zero": count = 0
            elif fault == "large": count = 65537
            elif fault == "alias": stages = (arrays[0], *stages[1:])
            elif fault == "component": component = 3
            before = [bytes(v) for v in stages]
            self.assertNotEqual(self.lib.yb_cached_process_chunk(pointer, component, *arrays, count, *stages), 0)
            self.assertEqual([bytes(v) for v in stages], before)

    def test_maximum_chunk_and_null_plan_output_alias_boundaries(self):
        _, mapping, nlq = self.fixture(); pointer = self.plan(mapping, nlq)
        n = 65536
        values = (C.c_uint16 * n)(*(i & 1023 for i in range(n)))
        actual, old = self.stages(n), self.stages(n)
        self.assertEqual(self.lib.yb_cached_process_chunk(pointer, 2, values, values,
            values, values, n, *actual), 0)
        self.assertEqual(self.lib.yb_process_chunk(C.byref(mapping), C.cast(C.byref(nlq, 2 * C.sizeof(NLQConfig)), C.POINTER(NLQConfig)), 2,
            values, values, values, values, n, 1, 12, *old), 0)
        self.assertEqual([bytes(v) for v in actual], [bytes(v) for v in old])
        small = (C.c_uint16 * 2)(512, 513)
        for fault in ("plan", "misaligned_plan", "plan_input", "null0", "null1", "null2", "null3", "cross_output", "partial_output"):
            stages = list(self.stages(2)); plan = pointer; y = small
            if fault == "plan": plan = None
            elif fault == "misaligned_plan": plan = C.c_void_p(pointer.value + 1)
            elif fault == "plan_input": y = C.cast(pointer, C.POINTER(C.c_uint16))
            elif fault.startswith("null"): stages[int(fault[-1])] = None
            elif fault == "cross_output": stages[3] = stages[0]
            elif fault == "partial_output":
                storage = (C.c_uint16 * 3)(12345, 12345, 12345)
                stages[0] = C.cast(storage, C.POINTER(C.c_uint16))
                stages[3] = C.cast(C.byref(storage, 2), C.POINTER(C.c_uint16))
                before_storage = bytes(storage)
                self.assertNotEqual(self.lib.yb_cached_process_chunk(plan, 0, y, small,
                    small, small, 2, *stages), 0)
                self.assertEqual(bytes(storage), before_storage)
                continue
            before = [bytes(v) if v is not None else None for v in stages]
            self.assertNotEqual(self.lib.yb_cached_process_chunk(plan, 0, y, small,
                small, small, 2, *stages), 0)
            self.assertEqual([bytes(v) if v is not None else None for v in stages], before)

    def test_create_failures_preserve_destination(self):
        _, mapping, nlq = self.fixture()
        for fault in ("map", "nlq", "enable", "depth", "invalid_map", "invalid_nlq", "denominator"):
            _, current, configs = self.fixture(); sentinel = C.c_void_p(12345)
            enabled, depth = 1, 12
            if fault == "enable": enabled = 2
            elif fault == "depth": depth = 8
            elif fault == "invalid_map": current.components[2].pivots[1] = 0
            elif fault == "invalid_nlq": configs[2].offset = 1024
            elif fault == "denominator": configs[2].denominator = 22
            self.assertNotEqual(self.lib.yb_cached_create(
                None if fault == "map" else C.byref(current),
                None if fault == "nlq" else configs, enabled, depth, C.byref(sentinel)), 0)
            self.assertEqual(sentinel.value, 12345)
        self.assertNotEqual(self.lib.yb_cached_create(C.byref(mapping), nlq, 1, 12, None), 0)
        before = bytes(mapping)
        alias = C.cast(C.byref(mapping), C.POINTER(C.c_void_p))
        self.assertNotEqual(self.lib.yb_cached_create(C.byref(mapping), nlq, 1, 12, alias), 0)
        self.assertEqual(bytes(mapping), before)
        before = bytes(nlq)
        alias = C.cast(C.byref(nlq), C.POINTER(C.c_void_p))
        self.assertNotEqual(self.lib.yb_cached_create(C.byref(mapping), nlq, 1, 12, alias), 0)
        self.assertEqual(bytes(nlq), before)

    def test_mixed_polynomial_mmr_segments_keep_pivot_selection(self):
        unit = 1 << 23
        mixed = {"pivots": [0, 512, 1023], "segments": [
            {"method": "polynomial", "coefficients": [128, unit]},
            {"method": "mmr", "constant": -unit // 2,
             "coefficients": [[unit, -unit, unit // 2, 0, 0, 0, 0]]}]}
        source = [polynomial([0, 1023], [0, unit]), mixed,
                  polynomial([0, 1023], [0, unit])]
        parameters = [dict(offset=512, slope=2048, threshold=7, maximum=1025)] * 3
        triples = [(i, i, 1023 - i) for i in range(1024)]
        pointer, _, _ = self.compare(source, 10, 23, parameters, 12, triples, list(range(1024)))
        self.assertEqual([self.lib.yb_cached_component_route(pointer, c) for c in range(3)], [1, 0, 1])

    def test_frame_association_counts_completion_and_copied_settings(self):
        _, mapping, nlq = self.fixture()
        descriptor = frame.Descriptor(1, 1, 2, 2, 12, 1)
        descriptor.frame_id[0] = 7
        token = (C.c_uint8 * 32)(7); bad = (C.c_uint8 * 32)(8)
        handle = C.c_void_p()
        self.assertEqual(self.lib.yb_cached_frame_create(C.byref(descriptor),
            C.byref(mapping), nlq, C.byref(handle)), 0)
        self.addCleanup(self.lib.yb_cached_frame_destroy, handle)
        descriptor.frame_id[0] = 99
        mapping.components[0].pivots[1] = 0
        completion = frame.Completion(); completion.kind = 12345
        self.assertEqual(self.lib.yb_cached_frame_finish(handle, C.byref(completion)), 5)
        self.assertEqual(completion.kind, 12345)
        inputs = (C.c_uint16 * 4)(512, 513, 511, 514)
        for fault, expected in (("token", 2), ("start", 5), ("count", 5)):
            stages = self.stages(4); before = [bytes(v) for v in stages]
            self.assertEqual(self.lib.yb_cached_frame_process(handle,
                bad if fault == "token" else token, 0, 1 if fault == "start" else 0,
                inputs, inputs, inputs, inputs, 5 if fault == "count" else 4, *stages), expected)
            self.assertEqual([bytes(v) for v in stages], before)
        for component, count in enumerate((4, 1, 1)):
            self.assertEqual(self.lib.yb_cached_frame_process(handle, token, component, 0,
                inputs, inputs, inputs, inputs, count, *self.stages(count)), 0)
        self.assertEqual(self.lib.yb_cached_frame_finish(handle, C.byref(completion)), 0)
        self.assertEqual((completion.kind, list(completion.counts)), (1, [4, 1, 1]))
        before = bytes(completion)
        self.assertEqual(self.lib.yb_cached_frame_finish(handle, C.byref(completion)), 7)
        self.assertEqual(bytes(completion), before)
        self.assertEqual(self.lib.yb_cached_frame_process(handle, token, 0, 0,
            inputs, inputs, inputs, inputs, 1, *self.stages(1)), 7)

    def test_frame_handle_token_and_output_aliases_are_rejected(self):
        _, mapping, nlq = self.fixture()
        descriptor = frame.Descriptor(1, 1, 2, 2, 12, 1)
        handle = C.c_void_p()
        self.assertEqual(self.lib.yb_cached_frame_create(C.byref(descriptor),
            C.byref(mapping), nlq, C.byref(handle)), 0)
        self.addCleanup(self.lib.yb_cached_frame_destroy, handle)
        token = (C.c_uint8 * 32)()
        inputs = (C.c_uint16 * 2)(512, 513)
        for fault in ("frame_token", "frame_output", "token_output"):
            stages = list(self.stages(2)); expected_token = token
            if fault == "frame_token": expected_token = C.cast(handle, C.POINTER(C.c_uint8))
            elif fault == "frame_output": stages[0] = C.cast(handle, C.POINTER(C.c_uint16))
            else: stages[0] = C.cast(token, C.POINTER(C.c_uint16))
            before = [bytes(v) for v in stages] if fault == "frame_token" else None
            self.assertEqual(self.lib.yb_cached_frame_process(handle, expected_token, 0, 0,
                inputs, inputs, inputs, inputs, 2, *stages), 2 if fault == "frame_token" else 8)
            if before is not None:
                self.assertEqual([bytes(v) for v in stages], before)
        self.assertEqual(self.lib.yb_cached_frame_finish(handle,
            C.cast(handle, C.POINTER(frame.Completion))), 8)
        # Failed calls have not advanced counts: the first valid start is zero.
        self.assertEqual(self.lib.yb_cached_frame_process(handle, token, 0, 0,
            inputs, inputs, inputs, inputs, 2, *self.stages(2)), 0)

    def test_frame_create_invalid_settings_preserve_handle(self):
        for fault in ("version", "raw", "geometry", "enabled", "depth", "nlq", "null"):
            _, mapping, nlq = self.fixture()
            descriptor = frame.Descriptor(1, 1, 2, 2, 12, 1)
            if fault == "version": descriptor.version = 2
            elif fault == "raw": descriptor.input_kind = 2
            elif fault == "geometry": descriptor.width = 3
            elif fault == "enabled": descriptor.enhancement_enabled = 2
            elif fault == "depth": descriptor.output_depth = 8
            elif fault == "nlq": nlq[2].denominator = 22
            sentinel = C.c_void_p(12345)
            self.assertNotEqual(self.lib.yb_cached_frame_create(
                None if fault == "null" else C.byref(descriptor), C.byref(mapping), nlq,
                C.byref(sentinel)), 0)
            self.assertEqual(sentinel.value, 12345)


if __name__ == "__main__": unittest.main()
