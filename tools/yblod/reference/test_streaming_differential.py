"""Compare every synthetic output stage with the unchanged whole-plane oracle."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from make_demo import make_demo
import reference
import streaming_composer


class StreamingDifferentialTests(unittest.TestCase):
    def compare(self, *, input_depth=10, output_depth=12, mmr=False, disabled=False,
                dimensions=None, chunks=(1, 3, 65536)):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "input"
            manifest = make_demo(bundle)
            metadata = manifest["metadata"]
            metadata["bl_bit_depth"] = input_depth
            metadata["el_bit_depth"] = input_depth
            metadata["output_bit_depth"] = output_depth
            metadata["disable_residual"] = disabled
            maximum = (1 << input_depth) - 1
            center = 1 << (input_depth - 1)
            for mapping in metadata["mappings"]:
                mapping["pivots"] = [0, center, maximum]
                mapping["segments"] = [
                    {"method": "polynomial", "coefficients": [131072, 524288, 262144]},
                    {"method": "polynomial", "coefficients": [0, 1 << 20]},
                ]
            metadata["nlq"] = [
                {"offset": center, "slope": 512, "threshold": 128, "maximum": 1025},
                {"offset": 1, "slope": 17, "threshold": 11, "maximum": 0},
                {"offset": maximum, "slope": 2048, "threshold": 0, "maximum": 1024},
            ]
            if mmr:
                # All three orders, including cubic cross-products and signs.
                for channel in (1, 2):
                    metadata["mappings"][channel]["segments"] = [
                        {"method": "mmr", "constant": 1 << 18,
                         "coefficients": [[0, 0, 0, 1 << 18, -(1 << 17), 1 << 16, 1 << 19],
                                          [0, 1 << 16, 0, 0, 0, 0, -(1 << 15)],
                                          [0, 0, 1 << 15, 0, 0, 0, 1 << 14]]}
                        for _ in range(2)
                    ]
                manifest["mmr_luma"] = "guide.u16le"
                (bundle / "guide.u16le").write_bytes(struct.pack("<2H", center - 1, maximum))
            values = {
                "bl_Y": (0, 1, center - 1, center, center + 1, maximum - 1, maximum, center),
                "bl_Cb": (center - 1, maximum), "bl_Cr": (1, center),
                "el_Y": (0, center - 2, center - 1, center, center + 1, center + 2, maximum, center),
                "el_Cb": (0, maximum), "el_Cr": (0, maximum),
            }
            for name, samples in values.items():
                (bundle / f"{name}.u16le").write_bytes(struct.pack("<" + "H" * len(samples), *samples))
            if dimensions is not None:
                width, height = dimensions
                manifest["width"], manifest["height"] = width, height
                for name, pattern in values.items():
                    count = width * height if name.endswith("_Y") else width * height // 4
                    samples = tuple(pattern[i % len(pattern)] for i in range(count))
                    (bundle / f"{name}.u16le").write_bytes(struct.pack("<" + "H" * count, *samples))
                if mmr:
                    count = width * height // 4
                    guide = tuple((center - 1, maximum)[i % 2] for i in range(count))
                    (bundle / "guide.u16le").write_bytes(struct.pack("<" + "H" * count, *guide))
            if disabled:
                manifest["el"] = None
            manifest_path = bundle / "frame.json"
            manifest_path.write_text(json.dumps(manifest))
            original = root / "reference"
            expected = reference.run(manifest_path, original)
            for chunk in chunks:
                destination = root / f"stream-{chunk}"
                actual = streaming_composer.run(manifest_path, destination, chunk_samples=chunk)
                self.assertEqual(actual["input_sha256"], expected["input_sha256"])
                self.assertEqual(actual["stages"], expected["stages"])
                for record in expected["stages"].values():
                    self.assertEqual((destination / record["file"]).read_bytes(),
                                     (original / record["file"]).read_bytes())

    def test_polynomial_intervals_and_both_input_output_depths(self):
        for input_depth in (8, 10):
            for output_depth in (10, 12):
                with self.subTest(input_depth=input_depth, output_depth=output_depth):
                    self.compare(input_depth=input_depth, output_depth=output_depth)

    def test_all_mmr_orders_and_explicit_luma_guide(self):
        for input_depth in (8, 10):
            with self.subTest(input_depth=input_depth):
                self.compare(input_depth=input_depth, mmr=True)

    def test_explicit_residual_disabled_with_mmr(self):
        self.compare(mmr=True, disabled=True)

    def test_larger_synthetic_bundle_crosses_many_chunk_boundaries(self):
        self.compare(mmr=True, dimensions=(256, 128), chunks=(17, 4096))


if __name__ == "__main__":
    unittest.main()
