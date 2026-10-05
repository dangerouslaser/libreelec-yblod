"""Independent synthetic P010-to-C reconstruction checks, not scaling rules.

Only synthetic instruction blobs are constructed here. Real decoder blobs must
remain opaque and come from the decoder; no real coefficients are fabricated.
"""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

import native_integration_frame as frame
from test_native_decoder_frame_bridge import Instructions

ROOT = Path(__file__).resolve().parent


class Surface(C.Structure):
    _fields_ = [("version", C.c_uint32), ("format", C.c_uint32),
                ("width", C.c_uint32), ("height", C.c_uint32),
                ("coherent_ready", C.c_uint32),
                ("allocation", C.POINTER(C.c_uint8)),
                ("allocation_bytes", C.c_uint64), ("y_offset", C.c_uint64),
                ("uv_offset", C.c_uint64), ("y_stride", C.c_uint64),
                ("uv_stride", C.c_uint64), ("frame_id", C.c_uint8 * 32),
                ("provenance_id", C.c_uint8 * 32)]


class SurfaceChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        library = Path(cls.directory.name) / "chain.so"
        subprocess.run(["cc", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall",
                        "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                        *(str(ROOT / p) for p in ("native_scaled_surface.c",
                        "native_decoder_frame_bridge.c", "native_integration_probe.c",
                        "native_composer.c", "native_sampling_probe.c")),
                        "-o", str(library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.yb_scaled_surface_sizeof_descriptor.restype = C.c_uint64
        cls.extract = cls.lib.yb_scaled_surface_extract
        cls.extract.argtypes = [C.POINTER(Surface), C.POINTER(C.c_uint8),
            C.POINTER(C.c_uint8), C.c_uint32, C.c_uint64, C.c_uint32,
            C.c_uint32, C.POINTER(C.c_uint16)]
        cls.extract.restype = C.c_int
        cls.init = cls.lib.yb_decoder_frame_bridge_init
        cls.init.argtypes = [C.POINTER(frame.Context), C.POINTER(frame.Descriptor),
                            C.c_void_p, C.c_size_t]
        cls.init.restype = C.c_int
        cls.integer = cls.lib.yb_integration_integer
        cls.integer.argtypes = [C.POINTER(frame.Context), C.POINTER(C.c_uint8),
            C.c_int32, C.c_uint64, *([C.POINTER(C.c_uint16)] * 4), C.c_uint32,
            C.POINTER(C.c_uint16), C.POINTER(C.c_int32), C.POINTER(C.c_int32),
            C.POINTER(C.c_uint16)]
        cls.integer.restype = C.c_int
        cls.finish = cls.lib.yb_integration_finish
        cls.finish.argtypes = [C.POINTER(frame.Context), C.POINTER(frame.Completion)]
        cls.finish.restype = C.c_int

    def fixture(self):
        # Padding is deliberately fractional and must never become a sample.
        allocation = (C.c_uint8 * 24)(*([255] * 24))
        values = ([0, 1023, 511, 514], [513], [510])
        for offset, code in zip((0, 2, 8, 10, 16, 18), sum((list(v) for v in values), [])):
            word = code * 64
            allocation[offset] = word & 255
            allocation[offset + 1] = word >> 8
        surface = Surface(1, 1, 2, 2, 1, allocation, 24, 0, 16, 8, 8)
        token = (C.c_uint8 * 32)(7)
        provenance = (C.c_uint8 * 32)(9)
        surface.frame_id[:] = token
        surface.provenance_id[:] = provenance
        instructions = Instructions()
        instructions.version = 1
        instructions.enabled = 1
        instructions.depth = 12
        instructions.mapping.bit_depth = 10
        instructions.mapping.denominator = 23
        for curve in instructions.mapping.components:
            curve.pivot_count = 2
            curve.pivots[1] = 1023
            curve.segments[0].order = 1
            curve.segments[0].coefficients[0][1] = 1 << 23
        for nlq in instructions.nlq:
            nlq.bit_depth = 10
            nlq.denominator = 23
            nlq.offset = 512
            nlq.maximum = 2048
            nlq.slope = 1024
        descriptor = frame.Descriptor(1, 1, 2, 2, 12, 1)
        descriptor.frame_id[:] = token
        descriptor.provenance_id[:] = provenance
        return allocation, surface, token, provenance, values, instructions, descriptor

    def output(self, n):
        return (C.c_uint16 * n)(*([12345] * n))

    def test_abi_and_exact_padded_interleaved_extraction(self):
        self.assertEqual(self.lib.yb_scaled_surface_sizeof_descriptor(), C.sizeof(Surface))
        allocation, surface, token, provenance, values, _, _ = self.fixture()
        for component, expected in enumerate(values):
            for mode, multiplier in ((1, 64), (2, 1)):
                output = self.output(len(expected))
                self.assertEqual(self.extract(C.byref(surface), token, provenance,
                    component, 0, len(expected), mode, output), 0)
                self.assertEqual(list(output), [v * multiplier for v in expected])

    def test_raw_fractional_preservation_and_exact_atomic_rejection(self):
        for fraction in (1, 16, 63):
            allocation, surface, token, provenance, _, _, _ = self.fixture()
            allocation[10] |= fraction  # Last Y sample, after earlier valid samples.
            output = self.output(4)
            self.assertEqual(self.extract(C.byref(surface), token, provenance, 0, 0, 4, 2, output), 4)
            self.assertEqual(list(output), [12345] * 4)
            self.assertEqual(self.extract(C.byref(surface), token, provenance, 0, 0, 4, 1, output), 0)
            self.assertEqual(output[3], 514 * 64 + fraction)

    def test_association_and_chunk_bounds_leave_output_unchanged(self):
        allocation, surface, token, provenance, _, _, _ = self.fixture()
        for fault, status in (("frame", 2), ("provenance", 2), ("start", 1), ("count", 1)):
            output = self.output(4)
            bad_frame = (C.c_uint8 * 32)(*token)
            bad_provenance = (C.c_uint8 * 32)(*provenance)
            if fault == "frame": bad_frame[31] = 1
            if fault == "provenance": bad_provenance[31] = 1
            self.assertEqual(self.extract(C.byref(surface), bad_frame, bad_provenance,
                0, 1 if fault == "start" else 0, 65537 if fault == "count" else 4,
                2, output), status)
            self.assertEqual(list(output), [12345] * 4)

    def test_complete_surface_bridge_chain_equals_direct_integer_input(self):
        allocation, surface, token, provenance, values, instructions, descriptor = self.fixture()
        contexts = [frame.Context(), frame.Context()]
        for context in contexts:
            self.assertEqual(self.init(C.byref(context), C.byref(descriptor),
                C.byref(instructions), C.sizeof(instructions)), 0)
        for component, expected in enumerate(values):
            n = len(expected)
            extracted = self.output(n)
            self.assertEqual(self.extract(C.byref(surface), token, provenance,
                component, 0, n, 2, extracted), 0)
            direct = (C.c_uint16 * n)(*expected)
            bl = (C.c_uint16 * n)(*([512] * n))
            all_stages = []
            for context, el in zip(contexts, (extracted, direct)):
                stages = (self.output(n), (C.c_int32 * n)(),
                          (C.c_int32 * n)(), self.output(n))
                self.assertEqual(self.integer(C.byref(context), token, component, 0,
                    bl, bl, bl, el, n, *stages), 0)
                all_stages.append([list(s) for s in stages])
            self.assertEqual(all_stages[0], all_stages[1])
            self.assertTrue(any(v != 0 for v in all_stages[0][1]))
        for context in contexts:
            completion = frame.Completion()
            self.assertEqual(self.finish(C.byref(context), C.byref(completion)), 0)
            self.assertEqual(list(completion.counts), [4, 1, 1])


if __name__ == "__main__":
    unittest.main()
