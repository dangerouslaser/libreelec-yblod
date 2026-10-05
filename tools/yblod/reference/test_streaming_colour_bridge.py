"""Synthetic bridge to the existing diagnostic colour path, not new DV colour rules."""
from pathlib import Path
import tempfile
import unittest

try:
    import numpy as np
except ImportError:
    np = None

from make_streaming_demo import make_demo
import reference
import streaming_composer
from known_answers import COLOUR_INPUTS, identity_source_transport
if np is not None:
    from inspect_composition import inspect
    from output_frame import convert, expand_left, pack


def identity_dm():
    # Explicit synthetic colour instructions; not an extracted RPU.
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
              signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
              signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 8192 if i % 4 == 0 else 0
        dm[f"rgb_to_lms_coef{i}"] = 16384 if i % 4 == 0 else 0
    for i in range(3):
        dm[f"ycc_to_rgb_offset{i}"] = 0
    return dm


@unittest.skipIf(np is None, "NumPy required for existing colour-path bridge")
class StreamingColourBridgeTests(unittest.TestCase):
    def test_synthetic_colour_conversion_against_decimal_oracle(self):
        values = list(COLOUR_INPUTS.values())
        actual = convert(np.array([values], dtype=np.uint16), identity_dm(), "direct", lambda *args: None)
        self.assertEqual(actual[0].tolist(), [list(identity_source_transport(v)) for v in values])

    def test_streamed_output_inspection_colour_and_strip_seams(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_demo(root / "input", width=32, height=18)
            original = reference.run(root / "input/frame.json", root / "original")
            streamed = streaming_composer.run(root / "input/frame.json", root / "streamed", chunk_samples=17)
            self.assertEqual(inspect(root / "original")["channels"], inspect(root / "streamed")["channels"])

            def planes(directory, report):
                result = []
                for channel, shape in (("Y", (18, 32)), ("Cb", (9, 16)), ("Cr", (9, 16))):
                    filename = report["stages"][f"reconstructed_{channel}"]["file"]
                    result.append(np.fromfile(directory / filename, dtype="<u2").reshape(shape))
                return result

            def colour(p, start=0, stop=18):
                ycc = np.stack([p[0][start:stop], expand_left(p[1], start, stop),
                                expand_left(p[2], start, stop)], axis=-1)
                saved = {}
                codes = convert(ycc, identity_dm(), "direct", lambda name, a: saved.update({name: a.copy()}))
                return codes, saved

            old_codes, old_stages = colour(planes(root / "original", original))
            new_planes = planes(root / "streamed", streamed)
            new_codes, new_stages = colour(new_planes)
            np.testing.assert_array_equal(old_codes, new_codes)
            for name in old_stages:
                np.testing.assert_array_equal(old_stages[name], new_stages[name])
            np.testing.assert_array_equal(pack(old_codes), pack(new_codes))
            for rows in (1, 7, 64):
                strips = np.concatenate([colour(new_planes, start, min(start + rows, 18))[0]
                                         for start in range(0, 18, rows)])
                np.testing.assert_array_equal(strips, new_codes)


if __name__ == "__main__":
    unittest.main()
