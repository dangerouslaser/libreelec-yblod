import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from make_streaming_demo import make_demo
import reference
import streaming_composer


class StreamingDemoTests(unittest.TestCase):
    def test_generator_chunk_invariance_and_pipeline_equality(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "first", root / "second"
            manifest = make_demo(first, width=32, height=18, chunk_samples=1)
            make_demo(second, width=32, height=18, chunk_samples=37)
            reference.validate(manifest)
            evidence = json.loads((first / "synthetic.json").read_text())
            for filename, digest in evidence["input_sha256"].items():
                data = (first / filename).read_bytes()
                self.assertEqual(data, (second / filename).read_bytes())
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            old = reference.run(first / "frame.json", root / "old")
            new = streaming_composer.run(first / "frame.json", root / "new", chunk_samples=17)
            self.assertEqual(old["stages"], new["stages"])
            self.assertEqual(new["input_sha256"], evidence["input_sha256"])

    def test_invalid_dimensions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kwargs in ({"width": True}, {"width": 3}, {"height": 0},
                           {"height": 4098}, {"chunk_samples": 0}, {"chunk_samples": True}):
                with self.assertRaises(ValueError): make_demo(root / "bad", **kwargs)
                self.assertFalse((root / "bad").exists())
            make_demo(root / "good", width=2, height=2)
            before = (root / "good/frame.json").read_bytes()
            with self.assertRaises(FileExistsError): make_demo(root / "good", width=2, height=2)
            self.assertEqual((root / "good/frame.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
