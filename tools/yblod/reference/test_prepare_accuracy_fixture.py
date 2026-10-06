import hashlib
import tempfile
import unittest
from pathlib import Path

from prepare_accuracy_fixture import manifest, verify_plane


class FixtureValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "plane.u16le"
        self.path.write_bytes(b"\0\0" * 4)
        self.record = dict(width=2, height=2,
                           sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_plane(self):
        verify_plane(self.path, self.record)

    def test_geometry_bound(self):
        with self.assertRaises(ValueError):
            verify_plane(self.path, dict(self.record, width=3841))

    def test_wrong_hash(self):
        with self.assertRaises(ValueError):
            verify_plane(self.path, dict(self.record, sha256="0" * 64))

    def test_wrong_size(self):
        with self.assertRaises(ValueError):
            verify_plane(self.path, dict(self.record, height=1))

    def test_symlink(self):
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            verify_plane(link, self.record)

    def test_manifest_bound(self):
        with self.assertRaises(ValueError):
            manifest(self.path.parent)


if __name__ == "__main__":
    unittest.main()
