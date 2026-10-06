import tempfile
import unittest
from pathlib import Path

from generate_ycc_workgroup_variants import GROUPS, LAYOUT, generate, variants


class WorkgroupVariants(unittest.TestCase):
    source = b"#version 430\n" + LAYOUT + b"\nvoid main(){}\n"

    def test_only_layout_changes(self):
        for text, (x, y) in zip(variants(self.source).values(), GROUPS):
            replacement = f"layout(local_size_x={x}, local_size_y={y}) in;".encode()
            self.assertEqual(text.replace(replacement, LAYOUT), self.source)

    def test_reject_missing_or_duplicate_layout(self):
        for source in (b"void main(){}", self.source + LAYOUT, self.source + b"\0"):
            with self.assertRaises(ValueError):
                variants(source)

    def test_fresh_output_and_preserved_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            shader = parent / "canonical.comp"
            shader.write_bytes(self.source)
            result = generate(shader, parent / "variants")
            self.assertEqual(len(result["variants"]), 3)
            self.assertEqual(shader.read_bytes(), self.source)
            with self.assertRaises(FileExistsError):
                generate(shader, parent / "variants")
            with self.assertRaises(FileExistsError):
                generate(shader, shader)

    def test_reject_symlink_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            shader = parent / "canonical.comp"
            shader.write_bytes(self.source)
            link = parent / "link.comp"
            link.symlink_to(shader)
            with self.assertRaises(ValueError):
                generate(link, parent / "variants")


if __name__ == "__main__":
    unittest.main()
