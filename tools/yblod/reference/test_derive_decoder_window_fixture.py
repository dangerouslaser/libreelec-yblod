import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from derive_decoder_window_fixture import derive, verify_aud_boundary


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.nal = b"\x7c\x01\x19\x80"

    def check(self, source, nal=None):
        nal = self.nal if nal is None else nal
        window, canonical, output = (self.root / name for name in ("window", "nal", "output"))
        window.write_bytes(source)
        canonical.write_bytes(nal)
        return derive(window, canonical, output,
                      window_sha256=hashlib.sha256(source).hexdigest(),
                      canonical_nal_sha256=hashlib.sha256(nal).hexdigest(),
                      packet_position=0, packet_size=len(source))

    def test_three_byte_start(self):
        source = b"\x00\x00\x01" + self.nal + b"\x00"
        result = self.check(source)
        self.assertEqual((self.root / "output").read_bytes(), source[:-1])
        self.assertEqual(result["removed_verified_eof_zero_bytes"], 1)
        self.assertEqual((self.root / "window").read_bytes(), source)

    def test_four_byte_start(self):
        source = b"\x00\x00\x00\x01" + self.nal + b"\x00"
        self.check(source)
        self.assertEqual((self.root / "output").read_bytes(), source[:-1])

    def test_zero_run_delimiter(self):
        source = b"\x00" * 6 + b"\x01" + self.nal + b"\x00"
        self.check(source)
        self.assertEqual((self.root / "output").read_bytes(), source[:-1])

    def test_two_zero_tail_rejected(self):
        with self.assertRaises(ValueError):
            self.check(b"\x00\x00\x01" + self.nal + b"\x00\x00")
        self.assertFalse((self.root / "output").exists())

    def test_nonzero_tail_rejected(self):
        with self.assertRaises(ValueError):
            self.check(b"\x00\x00\x01" + self.nal + b"\x01")

    def test_prefix_mutation_rejected(self):
        with self.assertRaises(ValueError):
            self.check(b"\x00\x00\x01\x7c\x01\x18\x80\x00")

    def test_no_overwrite(self):
        output = self.root / "output"
        output.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.check(b"\x00\x00\x01" + self.nal + b"\x00")
        self.assertEqual(output.read_bytes(), b"keep")

    def test_canonical_stop_rejected(self):
        with self.assertRaises(ValueError):
            self.check(b"\x00\x00\x01\x7c\x01\x19\x00\x00", b"\x7c\x01\x19\x00")

    def test_invalid_headers_rejected(self):
        for nal in (b"\xfc\x01\x19\x80", b"\x7d\x01\x19\x80", b"\x7c\x09\x19\x80", b"\x7c\x02\x19\x80"):
            with self.subTest(header=nal[:2]), self.assertRaises(ValueError):
                self.check(b"\x00\x00\x01" + nal + b"\x00", nal)

    def test_fifo_rejected_without_blocking(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            derive(fifo, self.root / "missing", self.root / "output",
                   window_sha256="0" * 64, canonical_nal_sha256="0" * 64,
                   packet_position=0, packet_size=1)

    def test_symlink_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.root / "missing")
        with self.assertRaises(OSError):
            derive(link, self.root / "missing", self.root / "output",
                   window_sha256="0" * 64, canonical_nal_sha256="0" * 64,
                   packet_position=0, packet_size=1)

    def test_wrong_hash_rejected(self):
        window = self.root / "window"
        window.write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            derive(window, self.root / "missing", self.root / "output",
                   window_sha256="0" * 64, canonical_nal_sha256="0" * 64,
                   packet_position=0, packet_size=1)

    def test_aud_boundary_prediction(self):
        source = b"\x00\x00\x00\x01\x46\x01\x50\x00\x00\x00\x01" + self.nal
        window = self.root / "derived"
        window.write_bytes(source)
        result = verify_aud_boundary(window, window_sha256=hashlib.sha256(source).hexdigest(),
                                     legacy_position=1, legacy_size=len(source))
        self.assertEqual(result["canonical_aud_position"], 0)
        self.assertEqual(result["canonical_packet_size"], len(source))

    def test_aud_wrong_type_rejected(self):
        source = b"\x00\x00\x00\x01\x44\x01\x50"
        window = self.root / "derived"
        window.write_bytes(source)
        with self.assertRaises(ValueError):
            verify_aud_boundary(window, window_sha256=hashlib.sha256(source).hexdigest(),
                                legacy_position=1, legacy_size=len(source))


if __name__ == "__main__":
    unittest.main()
