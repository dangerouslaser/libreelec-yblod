import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from compare_output import compare, crc32_mpeg2, decode_ce
from extract_frame import digest
from output_frame import TARGET_YCC, TARGET_LMS, pack


class ComparisonTests(unittest.TestCase):
    def fixture(self, root):
        codes = np.full((64, 128, 3), 2048, dtype=np.uint16)
        rgb = pack(codes)
        (root / "ours.rgb8").write_bytes(rgb.tobytes())
        payload = bytearray(200)
        payload[2:20] = np.rint(TARGET_YCC * 8192).astype(">i2").tobytes()
        payload[20:32] = np.array([0, 2**27, 2**27], dtype=">u4").tobytes()
        payload[32:50] = np.rint(TARGET_LMS * 16384).astype(">i2").tobytes()
        intensity = np.full(8192, 2048, dtype=int)
        chroma = intensity.copy()
        for pk in range(2):
            p = bytearray(128)
            p[0] = (1 if pk == 0 else 3) << 6
            if pk == 0:
                p[3:5] = len(payload).to_bytes(2, "big")
                p[5:124] = payload[:119]
            else:
                p[3:84] = payload[119:]
            p[124:] = crc32_mpeg2(p[:124]).to_bytes(4, "big")
            bits = np.unpackbits(np.frombuffer(p, dtype="u1"))
            for copy in range(3):
                for j, bit in enumerate(bits):
                    i = pk * 3072 + copy * 1024 + j
                    parity = (bin(int(chroma[i]) >> 1).count("1") + bin(int(intensity[i])).count("1")) & 1
                    chroma[i] = (chroma[i] & ~1) | (int(bit) ^ parity)
        wire = np.stack([chroma >> 4, intensity >> 4,
                         (intensity & 15) | ((chroma & 15) << 4)], axis=-1).astype("u1").reshape(64, 128, 3)
        # CoreELEC memory stores G,B,R then reverses each 64-bit word.
        native = wire[..., [1, 2, 0]].reshape(-1, 8)[:, ::-1]
        (root / "native.rgb").write_bytes(native.tobytes())
        identity = {"source_sha256": "abc", "visible_frame_number": 2296, "pts_us": 95762000}
        (root / "identity.json").write_text(json.dumps(identity))
        info = {"schema": "yblod.output-reference.v1", "status": "complete", "width": 128, "height": 64,
                "identity": {"frame_id": "abc:2296", "pts": 95762, "time_base": [1, 1000]},
                "active_rectangle": [0, 48, 128, 64], "policy": "direct",
                "stages": {"unembedded_tunnel": {"file": "ours.rgb8", "sha256": digest(root / "ours.rgb8")}}}
        (root / "output.json").write_text(json.dumps(info))
        return info

    def test_streamed_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            report = compare(root, root / "native.rgb", root / "identity.json")
            for channel in report["channels"].values():
                self.assertEqual(channel["mean_absolute_codes"], 0)

    def test_reject_wrong_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / "identity.json").write_text(json.dumps({"source_sha256": "wrong", "visible_frame_number": 2296}))
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                compare(root, root / "native.rgb", root / "identity.json")

    def test_reject_corrupt_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / "ours.rgb8").write_bytes(bytes(128*64*3))
            with self.assertRaisesRegex(ValueError, "integrity"):
                compare(root, root / "native.rgb", root / "identity.json")

    def test_reject_bad_capture_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / "native.rgb").write_bytes(bytes(128*64*3))
            with self.assertRaisesRegex(ValueError, "metadata packets"):
                compare(root, root / "native.rgb", root / "identity.json")


if __name__ == "__main__":
    unittest.main()
