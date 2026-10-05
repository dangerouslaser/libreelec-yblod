"""Synthetic bundle differential checks; BL mapping remains the reference's."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from make_demo import make_demo
import reference
from nlq_stage import NLQConfig
import composition_stage as stage


def read_u16(path):
    data = path.read_bytes()
    return struct.unpack("<" + "H" * (len(data) // 2), data)


class CompositionIntegrationTests(unittest.TestCase):
    def compare_bundle(self, *, output_depth=12, disabled=False, binding=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "input"
            manifest = make_demo(bundle)
            metadata = manifest["metadata"]
            metadata["output_bit_depth"] = output_depth
            metadata["disable_residual"] = disabled
            if binding:
                metadata["coefficient_log2_denom"] = 23
                for mapping in metadata["mappings"]:
                    mapping["segments"][0]["coefficients"] = [0, 1 << 23]
                metadata["nlq"] = [
                    {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1025},
                    {"offset": 128, "slope": 4096, "threshold": 7, "maximum": 1024},
                    {"offset": 768, "slope": 17, "threshold": 11, "maximum": 0},
                ]
                for channel, samples in (
                    ("Y", (0, 510, 511, 512, 513, 514, 1023, 512)),
                    ("Cb", (0, 1023)), ("Cr", (0, 1023)),
                ):
                    (bundle / f"el_{channel}.u16le").write_bytes(
                        struct.pack("<" + "H" * len(samples), *samples))
            if disabled:
                # Base-only operation must not read an enhancement plane.
                manifest["el"] = None
                for channel in reference.CHANNELS:
                    (bundle / f"el_{channel}.u16le").unlink()
            manifest_path = bundle / "frame.json"
            manifest_path.write_text(json.dumps(manifest))
            output = root / "reference"
            reference.run(manifest_path, output)
            for index, channel in enumerate(reference.CHANNELS):
                mapped = read_u16(output / f"mapped_{channel}.u16le")
                expected = read_u16(output / f"reconstructed_{channel}.u16le")
                if disabled:
                    actual = stage.iter_base_only(iter(mapped), output_depth)
                else:
                    config = NLQConfig.from_mapping(
                        metadata["nlq"][index], bit_depth=metadata["el_bit_depth"],
                        denominator=metadata["coefficient_log2_denom"])
                    enhancement = read_u16(bundle / f"el_{channel}.u16le")
                    actual = stage.iter_composed(iter(mapped), iter(enhancement), config, output_depth)
                self.assertEqual(tuple(actual), expected, channel)

    def test_existing_public_demo_both_output_depths(self):
        for depth in (10, 12):
            with self.subTest(depth=depth):
                self.compare_bundle(output_depth=depth)

    def test_binding_limits_and_distinct_channel_parameters(self):
        for depth in (10, 12):
            with self.subTest(depth=depth):
                self.compare_bundle(output_depth=depth, binding=True)

    def test_explicit_base_only_with_no_enhancement_files(self):
        for depth in (10, 12):
            with self.subTest(depth=depth):
                self.compare_bundle(output_depth=depth, disabled=True)


if __name__ == "__main__":
    unittest.main()
