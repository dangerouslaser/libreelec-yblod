"""CPU-readable P010 handoff; no device synchronization or fractional policy."""
import ctypes as C
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


class Surface(C.Structure):
    _fields_ = [("version", C.c_uint32), ("format", C.c_uint32),
                ("width", C.c_uint32), ("height", C.c_uint32),
                ("coherent_ready", C.c_uint32),
                ("allocation", C.POINTER(C.c_uint8)),
                *[(n, C.c_uint64) for n in ("allocation_bytes", "y_offset",
                    "uv_offset", "y_stride", "uv_stride")],
                ("frame_id", C.c_uint8 * 32), ("provenance_id", C.c_uint8 * 32)]


class ScaledSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(__file__).resolve().parent
        lib = Path(cls.tmp.name) / "surface.so"
        subprocess.run(["cc", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall",
                        "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                        *shlex.split(os.environ.get("YB_SURFACE_TEST_CFLAGS", "")),
                        str(root / "native_scaled_surface.c"), "-o", str(lib)],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(lib))
        cls.lib.yb_scaled_surface_extract.argtypes = [C.POINTER(Surface),
            C.POINTER(C.c_uint8), C.POINTER(C.c_uint8), C.c_uint32,
            C.c_uint64, C.c_uint32, C.c_uint32, C.POINTER(C.c_uint16)]
        cls.lib.yb_scaled_surface_extract.restype = C.c_int
        cls.lib.yb_scaled_surface_abi_version.restype = C.c_uint32
        cls.lib.yb_scaled_surface_sizeof_descriptor.restype = C.c_uint64

    def fixture(self):
        buf = (C.c_uint8 * 100)(*([0xAD] * 100))
        d = Surface(1, 1, 4, 4, 1, buf, 100, 4, 60, 12, 16)
        d.frame_id[0], d.provenance_id[0] = 7, 9
        frame, provenance = (C.c_uint8 * 32)(7), (C.c_uint8 * 32)(9)
        planes = [list(range(16)), [0, 1023, 19, 20], [1023, 0, 40, 41]]
        for c, values in enumerate(planes):
            for index, value in enumerate(values):
                self.write(buf, d, c, index, value << 6)
        return buf, d, frame, provenance, planes

    @staticmethod
    def write(buf, d, c, index, word):
        width = d.width // 2 if c else d.width
        offset = ((d.uv_offset if c else d.y_offset) +
                  (index // width) * (d.uv_stride if c else d.y_stride) +
                  (index % width) * (4 if c else 2) + (2 if c == 2 else 0))
        buf[offset], buf[offset + 1] = word & 255, word >> 8

    def extract(self, fixture, c=0, start=0, count=4, mode=1, out=None):
        _, d, frame, provenance, _ = fixture
        if out is None:
            out = (C.c_uint16 * count)(*([45678] * count))
        status = self.lib.yb_scaled_surface_extract(C.byref(d), frame, provenance,
                                                    c, start, count, mode, out)
        return status, out

    def test_abi(self):
        self.assertEqual(self.lib.yb_scaled_surface_abi_version(), 1)
        self.assertEqual(self.lib.yb_scaled_surface_sizeof_descriptor(), C.sizeof(Surface))

    def test_padded_offsets_interleaved_planes_and_last_rows(self):
        f = self.fixture()
        for c, values in enumerate(f[4]):
            for mode in (1, 2):
                status, out = self.extract(f, c, 0, len(values), mode)
                self.assertEqual(status, 0)
                self.assertEqual(list(out), [v << 6 for v in values] if mode == 1 else values)
        self.assertEqual(list(self.extract(f, 0, 13, 3, 2)[1]), [13, 14, 15])
        self.assertEqual(list(self.extract(f, 1, 1, 3, 2)[1]), [1023, 19, 20])

    def test_all_fractional_residues_reject_atomically_and_raw_preserves(self):
        for residue in range(1, 64):
            f = self.fixture()
            self.write(f[0], f[1], 0, 15, 65472 + residue)
            status, out = self.extract(f, 0, 0, 16, 2)
            self.assertEqual(status, 4)
            self.assertEqual(list(out), [45678] * 16)
            self.assertEqual(self.extract(f, 0, 15, 1, 1)[1][0], 65472 + residue)
            self.assertEqual(self.extract(f, 0, 0, 15, 2)[0], 0)

    def test_tokens_reject_without_writes(self):
        for position in (2, 3):
            f = self.fixture()
            f[position][31] = 1
            status, out = self.extract(f)
            self.assertEqual(status, 2)
            self.assertEqual(list(out), [45678] * 4)

    def test_invalid_geometry_spans_and_modes(self):
        changes = [("version", 0), ("format", 2), ("coherent_ready", 0),
                   ("coherent_ready", 2), ("width", 0), ("width", 3),
                   ("height", 8194), ("y_stride", 7), ("uv_stride", 9),
                   ("y_offset", 3), ("allocation_bytes", 83),
                   ("uv_offset", 2**64-2), ("y_stride", 2**64-2)]
        for name, value in changes:
            f = self.fixture()
            setattr(f[1], name, value)
            status, out = self.extract(f)
            self.assertEqual(status, 1, (name, value))
            self.assertEqual(list(out), [45678] * 4)
        for args in [(3, 0, 1, 1), (0, 16, 1, 1), (0, 2**64-1, 1, 1),
                     (0, 0, 0, 1), (0, 0, 65537, 1), (0, 0, 1, 0)]:
            self.assertEqual(self.extract(self.fixture(), *args)[0], 1)

    def test_allocation_wrap_and_null(self):
        for address in (0, 2**(C.sizeof(C.c_void_p)*8)-2):
            f = self.fixture()
            f[1].allocation = C.cast(C.c_void_p(address), C.POINTER(C.c_uint8))
            self.assertEqual(self.extract(f)[0], 1)

    def test_aliases_reject(self):
        f = self.fixture()
        out = C.cast(f[0], C.POINTER(C.c_uint16))
        original = bytes(f[0])
        self.assertEqual(self.extract(f, out=out)[0], 3)
        self.assertEqual(bytes(f[0]), original)
        f[1].uv_offset = 20
        self.assertEqual(self.extract(f)[0], 3)
        f = self.fixture()
        self.assertEqual(self.lib.yb_scaled_surface_extract(C.byref(f[1]),
            f[1].frame_id, f[3], 0, 0, 1, 1, (C.c_uint16 * 1)(123)), 3)
        self.assertEqual(self.lib.yb_scaled_surface_extract(C.byref(f[1]),
            f[2], f[2], 0, 0, 1, 1, (C.c_uint16 * 1)(123)), 3)

    def test_maximum_chunk_and_geometry(self):
        # Large declared geometry is cheap to test: exactly one 65536-sample
        # chunk, not a full 8192-square allocation or unbounded native loop.
        buf = (C.c_uint8 * (256 * 256 * 3))()
        d = Surface(1, 1, 256, 256, 1, buf, len(buf), 0, 131072, 512, 512)
        frame, provenance = (C.c_uint8 * 32)(), (C.c_uint8 * 32)()
        out = (C.c_uint16 * 65536)(*([123] * 65536))
        self.assertEqual(self.lib.yb_scaled_surface_extract(C.byref(d), frame,
                         provenance, 0, 0, 65536, 2, out), 0)
        self.assertEqual(set(out), {0})

    def test_descriptor_output_and_token_output_alias(self):
        f = self.fixture()
        before = bytes(f[1])
        out = C.cast(C.byref(f[1]), C.POINTER(C.c_uint16))
        self.assertEqual(self.extract(f, out=out)[0], 3)
        self.assertEqual(bytes(f[1]), before)
        out = C.cast(f[2], C.POINTER(C.c_uint16))
        self.assertEqual(self.extract(f, out=out)[0], 3)
        f[1].allocation = C.cast(C.byref(f[0], 1), C.POINTER(C.c_uint8))
        self.assertEqual(self.extract(f)[0], 1)


if __name__ == "__main__":
    unittest.main()
