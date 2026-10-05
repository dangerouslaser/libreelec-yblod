"""CPU-only proposed adapter; tests do not certify playback or GPU ownership."""
import ctypes as C
from fractions import Fraction
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_native_composer import MappingConfig, NLQConfig, native_mapping, polynomial
from test_native_sampling_probe import Plane, Contract, Query, Result


class Descriptor(C.Structure):
    _fields_ = [("version", C.c_uint32), ("input_kind", C.c_uint32),
                ("width", C.c_uint32), ("height", C.c_uint32),
                ("output_depth", C.c_int32), ("enhancement_enabled", C.c_int32),
                ("frame_id", C.c_uint8 * 32), ("provenance_id", C.c_uint8 * 32)]


class Context(C.Structure):
    _fields_ = [("initialized", C.c_uint32), ("finalized", C.c_uint32),
                ("descriptor", Descriptor), ("mapping", MappingConfig),
                ("nlq", NLQConfig * 3), ("sampling", Contract),
                ("consumed", C.c_uint64 * 3), ("diagnostic_queries", C.c_uint64)]


class Completion(C.Structure):
    _fields_ = [("kind", C.c_uint32), ("counts", C.c_uint64 * 3),
                ("diagnostic_queries", C.c_uint64)]


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(__file__).resolve().parent
        library = Path(cls.temporary.name) / "integration.so"
        subprocess.run(["cc", "-std=c11", "-O2", "-fPIC", "-shared", "-Wall",
                        "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                        *shlex.split(os.environ.get("YB_INTEGRATION_TEST_CFLAGS", "")),
                        *(str(root / name) for name in ("native_composer.c",
                          "native_sampling_probe.c", "native_integration_probe.c")),
                        "-o", str(library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        signatures = {
            "yb_integration_init": [C.POINTER(Context), C.POINTER(Descriptor),
                C.POINTER(MappingConfig), C.POINTER(NLQConfig), C.POINTER(Contract)],
            "yb_integration_integer": [C.POINTER(Context), C.POINTER(C.c_uint8),
                C.c_int32, C.c_uint64, *([C.POINTER(C.c_uint16)] * 4), C.c_uint32,
                C.POINTER(C.c_uint16), C.POINTER(C.c_int32), C.POINTER(C.c_int32),
                C.POINTER(C.c_uint16)],
            "yb_integration_raw": [C.POINTER(Context), C.POINTER(C.c_uint8),
                C.POINTER(Plane), C.POINTER(Query), C.c_uint64, C.POINTER(Result)],
            "yb_integration_finish": [C.POINTER(Context), C.POINTER(Completion)],
            "yb_integration_reset": [C.POINTER(Context)]}
        for name, arguments in signatures.items():
            fn = getattr(cls.lib, name)
            fn.argtypes = arguments
            fn.restype = None if name.endswith("reset") else C.c_int
        cls.lib.yb_integration_abi_version.argtypes = []
        cls.lib.yb_integration_abi_version.restype = C.c_uint32
        for name in ("descriptor", "context", "completion", "sampling_contract"):
            fn = getattr(cls.lib, "yb_integration_sizeof_" + name)
            fn.argtypes = []
            fn.restype = C.c_uint64

    def test_abi_queries(self):
        self.assertEqual(self.lib.yb_integration_abi_version(), 1)
        for name, structure in (("descriptor", Descriptor), ("context", Context),
                                ("completion", Completion), ("sampling_contract", Contract)):
            self.assertEqual(getattr(self.lib, "yb_integration_sizeof_" + name)(),
                             C.sizeof(structure))

    def fixture(self, enabled=True):
        context = Context()
        desc = Descriptor(1, 1, 2, 2, 12, int(enabled))
        desc.frame_id[0] = 7
        desc.provenance_id[0] = 9
        mapping = native_mapping([polynomial([0, 1023], [0, 1 << 23])] * 3)
        nlq = (NLQConfig * 3)(*(NLQConfig(10, 23, 512, 2048, 0, 1024)
                               for _ in range(3)))
        self.assertEqual(self.lib.yb_integration_init(C.byref(context), C.byref(desc),
                         C.byref(mapping), nlq if enabled else None, None), 0)
        return context, desc, mapping, nlq

    def dispatch(self, ctx, desc, component=0, start=0, codes=(512, 513, 511, 514),
                 el_codes=None):
        n = len(codes)
        inputs = (C.c_uint16 * n)(*codes)
        el = (C.c_uint16 * n)(*(el_codes or [512] * n))
        mapped = (C.c_uint16 * n)(*([12345] * n))
        residual = (C.c_int32 * n)(*([12345] * n))
        sums = (C.c_int32 * n)(*([12345] * n))
        output = (C.c_uint16 * n)(*([12345] * n))
        status = self.lib.yb_integration_integer(C.byref(ctx), desc.frame_id,
            component, start, inputs, inputs, inputs,
            el if ctx.descriptor.enhancement_enabled else None,
            n, mapped, residual, sums, output)
        return status, (mapped, residual, sums, output)

    def test_copied_metadata_exact_integer_stages_and_frame_completion(self):
        ctx, desc, mapping, nlq = self.fixture()
        mapping.bit_depth = 8
        nlq[0].maximum = 0
        desc.provenance_id[0] = 77
        status, stages = self.dispatch(ctx, desc, el_codes=[512, 513, 511, 514])
        self.assertEqual(status, 0)
        self.assertEqual([list(a) for a in stages],
            [[32768, 32832, 32704, 32896], [0, 8, -8, 8],
             [32768, 32840, 32696, 32904], [2048, 2053, 2044, 2057]])
        self.assertEqual(ctx.descriptor.provenance_id[0], 9)
        completion = Completion()
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), C.byref(completion)), 5)
        for component in (1, 2):
            self.assertEqual(self.dispatch(ctx, desc, component, codes=(512,))[0], 0)
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), C.byref(completion)), 0)
        self.assertEqual((completion.kind, list(completion.counts)), (1, [4, 1, 1]))
        before = bytes(completion)
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), C.byref(completion)), 7)
        self.assertEqual(bytes(completion), before)
        self.assertEqual(self.dispatch(ctx, desc)[0], 7)

    def test_partial_counts_invalid_late_sample_association_leave_state(self):
        ctx, desc, _, _ = self.fixture()
        for start, codes, expected in ((1, (512,), 5), (0, (512, 1024), 6),
                                       (0, (512,) * 5, 5), ((1 << 64) - 1, (512,), 5)):
            before = bytes(ctx)
            status, stages = self.dispatch(ctx, desc, start=start, codes=codes)
            self.assertEqual(status, expected)
            self.assertEqual(bytes(ctx), before)
            self.assertTrue(all(v == 12345 for a in stages for v in a))
        desc.frame_id[0] = 8
        self.assertEqual(self.dispatch(ctx, desc)[0], 2)
        desc.frame_id[0] = 7
        self.assertEqual(self.dispatch(ctx, desc, codes=(512,))[0], 0)
        self.assertEqual(self.dispatch(ctx, desc, codes=(512,))[0], 5)
        self.assertEqual(self.dispatch(ctx, desc, start=1, codes=(512, 512, 512))[0], 0)

    def test_disabled_is_explicit_not_missing_layer_fallback(self):
        ctx, desc, mapping, nlq = self.fixture(False)
        status, stages = self.dispatch(ctx, desc)
        self.assertEqual(status, 0)
        self.assertEqual(list(stages[1]), [0] * 4)
        original = bytes(ctx)
        self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                            C.byref(mapping), nlq, None), 0)
        self.assertEqual(bytes(ctx), original)

    def raw_fixture(self):
        ctx = Context()
        desc = Descriptor(1, 2, 3, 1, 0, 0)
        desc.frame_id[0] = 7
        contract = Contract(3, 1, 1, 0, 2, 2, 1, 2, 1, 10, 6, 65472)
        self.assertEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                         None, None, C.byref(contract)), 0)
        words = (C.c_uint16 * 3)(32768, 32784, 65535)
        plane = Plane(C.cast(C.c_void_p(C.addressof(words)), C.POINTER(C.c_uint16)),
                      3, 3, 1, 3)
        queries = (Query * 2)(Query(0, 0), Query(2, 0))
        results = (Result * 2)()
        return ctx, desc, contract, words, plane, queries, results

    def test_raw_diagnostic_preserves_precision_never_composes(self):
        ctx, desc, contract, words, plane, queries, results = self.raw_fixture()
        contract.word_normalization_divisor = 65535
        self.assertEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
            C.byref(plane), queries, 2, results), 0)
        self.assertEqual(Fraction(results[0].raw_numerator, results[0].raw_denominator), 32776)
        self.assertEqual(Fraction(results[0].raw_numerator, results[0].normalized_denominator),
                         Fraction(32776, 65472))
        self.assertGreater(results[1].raw_numerator, results[1].normalized_denominator)
        self.assertEqual(self.dispatch(ctx, desc)[0], 4)
        words[:] = [32768, 32832, 65472]
        self.assertEqual(self.dispatch(ctx, desc)[0], 4)
        completion = Completion()
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), C.byref(completion)), 0)
        self.assertEqual((completion.kind, completion.diagnostic_queries), (2, 2))
        self.assertEqual(list(completion.counts), [0, 0, 0])

    def test_raw_wrong_plane_late_query_overflow_and_unqueried_finish(self):
        ctx, desc, _, owner, plane, queries, results = self.raw_fixture()
        completion = Completion()
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), C.byref(completion)), 5)
        for fault in ("tile", "query", "overflow", "id"):
            ctx, desc, _, owner, plane, queries, results = self.raw_fixture()
            if fault == "tile": plane.width = 2
            if fault == "query": queries[1].x = 8192
            if fault == "overflow": ctx.diagnostic_queries = (1 << 64) - 1
            if fault == "id": desc.frame_id[0] = 8
            before, out = bytes(ctx), bytes(results)
            self.assertNotEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                C.byref(plane), queries, 2, results), 0)
            self.assertEqual(bytes(ctx), before)
            self.assertEqual(bytes(results), out)

    def test_alias_invalid_initialization_reset_and_routes(self):
        ctx, desc, mapping, nlq = self.fixture()
        before = bytes(ctx)
        self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                            C.byref(mapping), None, None), 0)
        self.assertEqual(bytes(ctx), before)
        for name, value in (("version", 2), ("input_kind", 3), ("width", 3),
                            ("height", 8194), ("enhancement_enabled", 2), ("output_depth", 8)):
            original = getattr(desc, name)
            setattr(desc, name, value)
            self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                C.byref(mapping), nlq, None), 0)
            self.assertEqual(bytes(ctx), before)
            setattr(desc, name, original)
        nlq[2].denominator = 22
        self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                           C.byref(mapping), nlq, None), 0)
        self.assertEqual(bytes(ctx), before)
        values = (C.c_uint16 * 4)(512, 512, 512, 512)
        residual = (C.c_int32 * 4)()
        sums = (C.c_int32 * 4)()
        output = (C.c_uint16 * 4)()
        alias = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(C.c_uint16))
        self.assertEqual(self.lib.yb_integration_integer(C.byref(ctx), desc.frame_id,
            0, 0, values, values, values, values, 4, alias, residual, sums, output), 8)
        self.assertEqual(bytes(ctx), before)
        self.assertEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                         None, None, 1, None), 3)
        completion_alias = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(Completion))
        self.assertEqual(self.lib.yb_integration_finish(C.byref(ctx), completion_alias), 8)
        self.assertEqual(bytes(ctx), before)
        self.lib.yb_integration_reset(C.byref(ctx))
        self.assertEqual(bytes(ctx), bytes(C.sizeof(ctx)))
        self.assertEqual(self.dispatch(ctx, desc)[0], 1)

    def test_null_misalignment_and_wrapping_addresses_before_dereference(self):
        ctx, desc, mapping, nlq = self.fixture()
        maximum = (1 << (C.sizeof(C.c_void_p) * 8)) - 1

        def forged(structure, address):
            return C.cast(C.c_void_p(address), C.POINTER(structure))

        bad_contexts = [None, forged(Context, C.addressof(ctx) + 1),
                        forged(Context, maximum - (maximum % C.alignment(Context)))]
        completion = Completion()
        for bad in bad_contexts:
            self.assertNotEqual(self.lib.yb_integration_finish(bad, C.byref(completion)), 0)
            self.assertNotEqual(self.lib.yb_integration_integer(bad, desc.frame_id,
                0, 0, None, None, None, None, 1, None, None, None, None), 0)
            self.assertNotEqual(self.lib.yb_integration_raw(bad, desc.frame_id,
                              None, None, 1, None), 0)
            self.lib.yb_integration_reset(bad)

        before = bytes(ctx)
        for bad in (None, forged(Descriptor, C.addressof(desc) + 1),
                    forged(Descriptor, maximum - (maximum % C.alignment(Descriptor)))):
            self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), bad,
                                C.byref(mapping), nlq, None), 0)
            self.assertEqual(bytes(ctx), before)
        for bad in (None, forged(MappingConfig, C.addressof(mapping) + 1),
                    forged(MappingConfig, maximum - (maximum % C.alignment(MappingConfig)))):
            self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), C.byref(desc),
                                bad, nlq, None), 0)
            self.assertEqual(bytes(ctx), before)
        wrapping_id = forged(C.c_uint8, maximum - 15)
        self.assertEqual(self.lib.yb_integration_integer(C.byref(ctx), wrapping_id,
            0, 0, None, None, None, None, 1, None, None, None, None), 2)
        self.assertEqual(bytes(ctx), before)

        ctx, desc, contract, owner, plane, queries, results = self.raw_fixture()
        before, out = bytes(ctx), bytes(results)
        for bad in (None, forged(Plane, C.addressof(plane) + 1),
                    forged(Plane, maximum - (maximum % C.alignment(Plane)))):
            self.assertNotEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                                bad, queries, 2, results), 0)
            self.assertEqual(bytes(ctx), before)
            self.assertEqual(bytes(results), out)
        for bad_queries, bad_results in (
                (None, results), (queries, None),
                (forged(Query, C.addressof(queries) + 1), results),
                (queries, forged(Result, C.addressof(results) + 1)),
                (forged(Query, maximum - (maximum % C.alignment(Query))), results),
                (queries, forged(Result, maximum - (maximum % C.alignment(Result))))):
            self.assertNotEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                               C.byref(plane), bad_queries, 2, bad_results), 0)
            self.assertEqual(bytes(ctx), before)
            self.assertEqual(bytes(results), out)
        self.assertEqual(self.lib.yb_integration_raw(C.byref(ctx), wrapping_id,
                         C.byref(plane), queries, 2, results), 2)

    def test_overlap_matrix_and_enabled_missing_el_fail_without_writes(self):
        ctx, desc, mapping, nlq = self.fixture()
        before = bytes(ctx)
        for target in ("mapping", "nlq", "descriptor"):
            pointer = C.c_void_p(C.addressof(ctx))
            m = C.cast(pointer, C.POINTER(MappingConfig)) if target == "mapping" else C.byref(mapping)
            n = C.cast(pointer, C.POINTER(NLQConfig)) if target == "nlq" else nlq
            d = C.cast(pointer, C.POINTER(Descriptor)) if target == "descriptor" else C.byref(desc)
            self.assertNotEqual(self.lib.yb_integration_init(C.byref(ctx), d, m, n, None), 0)
            self.assertEqual(bytes(ctx), before)
        values = (C.c_uint16 * 4)(512, 512, 512, 512)
        mapped = (C.c_uint16 * 4)(*([12345] * 4))
        residual = (C.c_int32 * 4)(*([12345] * 4))
        sums = (C.c_int32 * 4)(*([12345] * 4))
        output = (C.c_uint16 * 4)(*([12345] * 4))
        self.assertEqual(self.lib.yb_integration_integer(C.byref(ctx), desc.frame_id,
            0, 0, values, values, values, None, 4, mapped, residual, sums, output), 6)
        self.assertEqual(bytes(ctx), before)
        self.assertTrue(all(v == 12345 for a in (mapped, residual, sums, output) for v in a))
        for target in ("mapped", "residual", "sum", "reconstructed", "input"):
            u16 = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(C.c_uint16))
            i32 = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(C.c_int32))
            args = [u16 if target == "input" else values, values, values, values, 4,
                    u16 if target == "mapped" else mapped,
                    i32 if target == "residual" else residual,
                    i32 if target == "sum" else sums,
                    u16 if target == "reconstructed" else output]
            self.assertEqual(self.lib.yb_integration_integer(C.byref(ctx), desc.frame_id,
                             0, 0, *args), 8)
            self.assertEqual(bytes(ctx), before)
        ctx, desc, contract, owner, plane, queries, results = self.raw_fixture()
        before = bytes(ctx)
        alias = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(Result))
        self.assertEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                         C.byref(plane), queries, 2, alias), 8)
        self.assertEqual(bytes(ctx), before)
        original_data = plane.data
        plane.data = C.cast(C.c_void_p(C.addressof(ctx)), C.POINTER(C.c_uint16))
        self.assertEqual(self.lib.yb_integration_raw(C.byref(ctx), desc.frame_id,
                         C.byref(plane), queries, 2, results), 8)
        plane.data = original_data
        self.assertEqual(bytes(ctx), before)


if __name__ == "__main__":
    unittest.main()
