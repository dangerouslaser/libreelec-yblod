import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import colour_frame as frame
from make_streaming_demo import make_demo
import streaming_composer
from make_colour_demo import make_configuration
from test_colour_stage import dm_identity, TARGET_YCC, TARGET_LMS

try:
    import numpy as np
except ImportError:
    np = None


class ColourFrameTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        make_demo(self.root / "input", width=32, height=18)
        self.result = self.root / "result"
        streaming_composer.run(self.root / "input/frame.json", self.result, chunk_samples=17)
        self.config = dict(schema="yblod.colour-frame-config.v1",
            composer_report_sha256=hashlib.sha256((self.result / "report.json").read_bytes()).hexdigest(),
            source_dm=dm_identity(), target_ycc=TARGET_YCC, target_lms=TARGET_LMS,
            target_offset=[0, .5, .5], pq_policy="extend-positive-negative-to-zero",
            code_scale=4096, chroma_expansion="bilinear-left-diagnostic",
            active_rectangle=[0, 0, 32, 18], outside_codes=[0, 2048, 2048])
        self.config_path = self.root / "colour.json"
        self.output = self.root / "colour"

    def save(self):
        self.config_path.write_text(json.dumps(self.config))

    def test_output_sizes_hashes_and_bounded_cache(self):
        self.save()
        original = frame.Plane.row
        def bounded(plane, index):
            values = original(plane, index)
            self.assertLessEqual(len(plane.cache), 2)
            self.assertEqual(len(values), plane.width)
            return values
        with mock.patch.object(frame.Plane, "row", bounded):
            report = frame.run(self.result, self.config_path, self.output)
        self.assertEqual(report["source_dm_association"], "caller-declared, not verified against an extracted RPU")
        for record in report["stages"].values():
            raw = (self.output / record["file"]).read_bytes()
            self.assertEqual(len(raw), record["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
        self.assertTrue((self.output / "output.json").exists())

    def test_binding_and_explicit_choices_reject_before_output(self):
        for name, value in (("composer_report_sha256", "wrong"), ("chroma_expansion", "automatic"),
                            ("active_rectangle", [1, 0, 32, 18]), ("outside_codes", [0, True, 0]),
                            ("pq_policy", "automatic")):
            old = self.config[name]
            self.config[name] = value
            self.save()
            with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
            self.assertFalse(self.output.exists())
            self.config[name] = old

    def test_stage_corruption_path_escape_and_no_overwrite(self):
        self.save()
        report_path = self.result / "report.json"
        report = json.loads(report_path.read_text())
        path = self.result / report["stages"]["reconstructed_Y"]["file"]
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
        self.assertFalse(self.output.exists())
        path.write_bytes(raw)
        self.output.mkdir()
        (self.output / "sentinel").write_text("unchanged")
        with self.assertRaises(FileExistsError): frame.run(self.result, self.config_path, self.output)
        self.assertEqual((self.output / "sentinel").read_text(), "unchanged")
        report["stages"]["reconstructed_Y"]["file"] = "../escape"
        report_path.write_text(json.dumps(report))
        self.config["composer_report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        self.save()
        with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.root / "escaped")

    def test_failure_never_publishes_completion(self):
        self.save()
        with mock.patch.object(frame.colour_stage, "convert_sample", side_effect=ValueError("test policy failure")):
            with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
        self.assertFalse((self.output / "output.json").exists())
        with mock.patch.object(frame.os, "link", side_effect=OSError("test publication failure")):
            with self.assertRaises(OSError): frame.run(self.result, self.config_path, self.root / "publication")
        self.assertFalse((self.root / "publication/output.json").exists())

    def test_verified_claim_requires_evidence_and_exact_association(self):
        self.config["source_association"] = "verified-extracted-rpu"
        self.save()
        with self.assertRaisesRegex(ValueError, "requires extraction"):
            frame.run(self.result, self.config_path, self.output)
        self.assertFalse(self.output.exists())
        evidence = dict(source_dm=self.config["source_dm"],
            composer_report_sha256=self.config["composer_report_sha256"],
            identity={"frame_id": "synthetic-proof", "pts": 0, "time_base": [1, 24]},
            provenance={"test": "explicit mock, helper separately tested"},
            active_rectangle=self.config["active_rectangle"])
        self.config["source_identity"] = evidence["identity"]
        self.config["source_provenance"] = evidence["provenance"]
        self.save()
        with mock.patch("colour_metadata.load", return_value=evidence):
            report = frame.run(self.result, self.config_path, self.output, extraction=self.root / "evidence")
        self.assertIsNotNone(report["source_provenance"])
        evidence["composer_report_sha256"] = "different"
        with mock.patch("colour_metadata.load", return_value=evidence):
            with self.assertRaisesRegex(ValueError, "changed between"):
                frame.run(self.result, self.config_path, self.root / "changed", extraction=self.root / "evidence")
        evidence["composer_report_sha256"] = self.config["composer_report_sha256"]
        self.config["source_dm"]["ycc_to_rgb_coef0"] += 1
        self.save()
        # Evidence must be independently re-read, not trusted from the config.
        evidence["source_dm"] = dm_identity()
        with mock.patch("colour_metadata.load", return_value=evidence):
            with self.assertRaisesRegex(ValueError, "source_dm"):
                frame.run(self.result, self.config_path, self.root / "tampered", extraction=self.root / "evidence")

    def test_explicit_active_area_and_packing(self):
        self.config["active_rectangle"] = [2, 1, 30, 17]
        self.save()
        frame.run(self.result, self.config_path, self.output)
        codes = struct.unpack("<" + "H" * (32 * 18 * 3), (self.output / "transport_ipt444.u16le").read_bytes())
        packed = (self.output / "unembedded_tunnel.rgb8").read_bytes()
        for y in range(18):
            for x in range(32):
                start = (y * 32 + x) * 3
                pixel = codes[start:start+3]
                if not (2 <= x < 30 and 1 <= y < 17):
                    self.assertEqual(pixel, (0, 2048, 2048))
                intensity = (packed[start+1] << 4) | (packed[start+2] & 15)
                chroma = (packed[start] << 4) | (packed[start+2] >> 4)
                self.assertEqual(intensity, pixel[0])
                even = (y * 32 + x - x % 2) * 3
                self.assertEqual(chroma, codes[even + (1 if x % 2 == 0 else 2)])

    def test_synthetic_configuration_helper_and_no_overwrite(self):
        cfg = make_configuration(self.result, self.config_path, target="project-transport-diagnostic",
                                 pq_policy="extend-positive-negative-to-zero")
        self.assertEqual(cfg["composer_report_sha256"], self.config["composer_report_sha256"])
        report = frame.run(self.result, self.config_path, self.output)
        self.assertEqual(report["configuration"]["synthetic_target"], "project-transport-diagnostic")
        with self.assertRaises(FileExistsError):
            make_configuration(self.result, self.config_path, target="identity-diagnostic", pq_policy="reject-outside-unit")
        original = self.result / "report.json"
        changed = json.loads(original.read_text())
        changed["input_manifest"]["metadata"]["frame_id"] = "real-video"
        original.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            make_configuration(self.result, self.root / "bad.json", target="identity-diagnostic", pq_policy="reject-outside-unit")

    def test_changed_stage_and_cleanup_after_publication(self):
        self.save()
        original = frame.Plane.row
        changed = False
        def modify(plane, index):
            nonlocal changed
            row = original(plane, index)
            if not changed:
                raw = plane.path.read_bytes()
                plane.path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                changed = True
            return row
        with mock.patch.object(frame.Plane, "row", modify):
            with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
        self.assertFalse((self.output / "output.json").exists())
        # Use fresh reconstructed planes after the deliberately mutated fixture.
        fresh = self.root / "fresh"
        streaming_composer.run(self.root / "input/frame.json", fresh)
        self.config["composer_report_sha256"] = hashlib.sha256((fresh / "report.json").read_bytes()).hexdigest()
        self.save()
        original_unlink = Path.unlink
        def fail_pending(path, *args, **kwargs):
            if path.name == "output.pending.json": raise OSError("test pending cleanup")
            return original_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", fail_pending):
            report = frame.run(fresh, self.config_path, self.root / "successful")
        self.assertEqual(report["status"], "complete")
        self.assertTrue((self.root / "successful/output.json").exists())

    def test_unsupported_depth_and_nonregular_stage(self):
        path = self.result / "report.json"
        report = json.loads(path.read_text())
        original = path.read_bytes()
        report["input_manifest"]["metadata"]["output_bit_depth"] = 10
        path.write_text(json.dumps(report))
        self.config["composer_report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()
        with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
        self.assertFalse(self.output.exists())
        path.write_bytes(original)
        report = json.loads(original)
        os.mkfifo(self.result / "fifo")
        report["stages"]["reconstructed_Y"]["file"] = "fifo"
        path.write_text(json.dumps(report))
        self.config["composer_report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()
        with self.assertRaises(ValueError): frame.run(self.result, self.config_path, self.output)
        self.assertFalse(self.output.exists())

    @unittest.skipIf(np is None, "NumPy required for older diagnostic comparison")
    def test_exact_codes_against_existing_colour_helpers(self):
        from output_frame import convert, expand_left, pack
        self.save()
        frame.run(self.result, self.config_path, self.output)
        planes = []
        for channel, shape in (("Y", (18, 32)), ("Cb", (9, 16)), ("Cr", (9, 16))):
            planes.append(np.fromfile(self.result / f"reconstructed_{channel}.u16le", dtype="<u2").reshape(shape))
        expanded = np.stack([planes[0], expand_left(planes[1]), expand_left(planes[2])], axis=-1)
        expected = convert(expanded, dm_identity(), "direct", lambda *args: None)
        self.assertEqual((self.output / "transport_ipt444.u16le").read_bytes(), expected.astype("<u2").tobytes())
        self.assertEqual((self.output / "unembedded_tunnel.rgb8").read_bytes(), pack(expected).tobytes())


if __name__ == "__main__":
    unittest.main()
