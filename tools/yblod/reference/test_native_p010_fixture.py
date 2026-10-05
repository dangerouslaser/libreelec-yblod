"""Synthetic-only CLI safety/byte-order tests for diagnostic native10 packing."""
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest


class NativeP010FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / "packer"
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a C compiler is required")
        source = Path(__file__).with_name("native_p010_fixture.c")
        subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-Wconversion", "-Wshadow", str(source), "-o", str(cls.binary)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.planes = [self.root / x for x in ("y", "cb", "cr")]
        self.out = self.root / "output"
        self.make(4, 2)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, width, height):
        self.width, self.height = width, height
        self.codes = [[(0, 1, 512, 1023)[i % 4] for i in range(width * height)],
                      [64 + i % 900 for i in range(width * height // 4)],
                      [960 - i % 900 for i in range(width * height // 4)]]
        for path, values in zip(self.planes, self.codes):
            path.write_bytes(struct.pack("<" + "H" * len(values), *values))

    def run_packer(self, *, planes=None, output=None, dims=None):
        return subprocess.run([str(self.binary), *(str(x) for x in (planes or self.planes)),
                               str(output or self.out), *(str(x) for x in (dims or (self.width, self.height)))],
                              capture_output=True, timeout=5)

    def test_extrema_order_multiple_dimensions(self):
        for width, height in ((2, 2), (4, 2), (6, 4), (64, 32)):
            with self.subTest(width=width, height=height):
                self.make(width, height)
                if self.out.exists():
                    self.out.unlink()
                result = self.run_packer()
                self.assertEqual(result.returncode, 0, result.stderr)
                words = self.codes[0] + [value for pair in zip(self.codes[1], self.codes[2]) for value in pair]
                self.assertEqual(self.out.read_bytes(), struct.pack("<" + "H" * len(words), *(x << 6 for x in words)))
                self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)

    def test_wrong_size_each_plane(self):
        for index in range(3):
            with self.subTest(index=index):
                self.make(4, 2)
                self.planes[index].write_bytes(self.planes[index].read_bytes() + b"\0")
                self.assertNotEqual(self.run_packer().returncode, 0)
                self.assertFalse(self.out.exists())

    def test_late_bad_code_removes_owned_output(self):
        for index in range(3):
            with self.subTest(index=index):
                self.make(4, 2)
                data = self.planes[index].read_bytes()
                self.planes[index].write_bytes(data[:-2] + struct.pack("<H", 1024))
                self.assertNotEqual(self.run_packer().returncode, 0)
                self.assertFalse(self.out.exists())

    def test_existing_output_preserved(self):
        self.out.write_bytes(b"existing")
        self.assertNotEqual(self.run_packer().returncode, 0)
        self.assertEqual(self.out.read_bytes(), b"existing")

    def test_input_symlink_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.planes[0])
        self.assertNotEqual(self.run_packer(planes=[link, *self.planes[1:]]).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_output_symlink_preserved(self):
        self.out.symlink_to(self.planes[0])
        old = self.planes[0].read_bytes()
        self.assertNotEqual(self.run_packer().returncode, 0)
        self.assertTrue(self.out.is_symlink())
        self.assertEqual(self.planes[0].read_bytes(), old)

    def test_fifo_input_does_not_hang(self):
        pipe = self.root / "pipe"
        os.mkfifo(pipe)
        self.assertNotEqual(self.run_packer(planes=[pipe, *self.planes[1:]]).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_aliased_sources_rejected(self):
        self.assertNotEqual(self.run_packer(planes=[self.planes[0], self.planes[1], self.planes[1]]).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_bad_dimensions(self):
        for dims in ((0, 2), (3, 2), (8194, 2), ("+2", 2), (" 2", 2), ("2x", 2), ("", 2), ("999999999999999", 2)):
            with self.subTest(dims=dims):
                self.assertNotEqual(self.run_packer(dims=dims).returncode, 0)
                self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
