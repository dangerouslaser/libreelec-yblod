import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import colour_metadata as metadata
from import_rpu import normalize
from make_demo import make_demo
from test_import_rpu import synthetic_rpu
from test_colour_stage import dm_identity, IDENTITY


class ColourMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result = self.root / "result"
        self.extraction = self.root / "extraction"
        self.result.mkdir()
        self.extraction.mkdir()
        self.manifest = make_demo(self.root / "prepared")
        self.identity = dict(frame_id="a" * 64 + ":17", pts=100, time_base=[1, 1000])
        self.rpu = synthetic_rpu()
        self.rpu["vdr_dm_data"] = dm_identity()
        self.rpu["vdr_dm_data"]["cmv29_metadata"] = {
            "num_ext_blocks": 1, "ext_metadata_blocks": [{"Level5": {
                f"active_area_{side}_offset": 0 for side in ("left", "right", "top", "bottom")}}]}
        self.extracted = dict(schema="yblod.extracted-frame.v1", status="complete",
            source_sha256="a" * 64, source_packet_index_zero_based=17, pts=100, time_base=[1, 1000],
            rpu_matches_source_packet_and_global_index=True, layers={"bl": {"width": 4, "height": 2}})
        for layer in ("bl", "el"):
            self.manifest[layer].update(self.identity)
        self.manifest["metadata"] = normalize(self.rpu, self.identity)
        self.manifest["preparation_details"] = {}
        self.binary = b"synthetic opaque RPU bytes; not a real Dolby packet"
        self.refresh()

    def write_json(self, path, value):
        data = json.dumps(value).encode()
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def refresh(self):
        self.extracted["rpu_json_sha256"] = self.write_json(self.extraction / "rpu.json", self.rpu)
        (self.extraction / "frame.rpu.bin").write_bytes(self.binary)
        self.extracted["rpu_sha256"] = hashlib.sha256(self.binary).hexdigest()
        extraction_hash = self.write_json(self.extraction / "extraction.json", self.extracted)
        self.manifest["preparation_details"]["source_extraction_sha256"] = extraction_hash
        self.write_json(self.result / "report.json", {
            "schema": "yblod.composer-result.v1", "status": "complete", "input_manifest": self.manifest})

    def test_verified_metadata_and_explicit_scope(self):
        result = metadata.load(self.result, self.extraction)
        self.assertEqual(result["source_dm"], self.rpu["vdr_dm_data"])
        self.assertEqual(result["identity"], self.identity)
        self.assertEqual(result["active_rectangle"], [0, 0, 4, 2])
        self.assertEqual(result["provenance"]["association"], "verified-extracted-rpu")
        self.assertIs(result["provenance"]["normalization_exact"], True)
        self.assertEqual(result["composer_report_sha256"], hashlib.sha256((self.result / "report.json").read_bytes()).hexdigest())
        self.assertIn("not authenticity", result["provenance"]["scope"])

    def test_raw_parsed_and_extraction_hash_tamper(self):
        for filename in ("frame.rpu.bin", "rpu.json", "extraction.json"):
            self.refresh()
            path = self.extraction / filename
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ValueError, msg=filename): metadata.load(self.result, self.extraction)

    def test_normalized_instructions_must_match(self):
        self.rpu["rpu_data_mapping"]["nlq"]["linear_deadzone_slope"][1] += 1
        self.refresh()
        with self.assertRaisesRegex(ValueError, "normalized"): metadata.load(self.result, self.extraction)

    def test_source_identity_and_geometry_not_just_digest(self):
        original = copy.deepcopy(self.extracted)
        for key, value in (("source_packet_index_zero_based", 18), ("pts", 101),
                           ("time_base", [1, 24]), ("source_sha256", "b" * 64),
                           ("source_packet_index_zero_based", True), ("source_sha256", "invalid")):
            self.extracted = copy.deepcopy(original)
            self.extracted[key] = value
            self.refresh()
            with self.assertRaises(ValueError, msg=key): metadata.load(self.result, self.extraction)
        self.extracted = copy.deepcopy(original)
        self.extracted["layers"]["bl"]["width"] = 8
        self.refresh()
        with self.assertRaisesRegex(ValueError, "geometry"): metadata.load(self.result, self.extraction)

    def test_incomplete_and_nonboolean_verification_rejected(self):
        for key, value in (("status", "failed"), ("rpu_matches_source_packet_and_global_index", False),
                           ("rpu_matches_source_packet_and_global_index", 1)):
            original = self.extracted[key]
            self.extracted[key] = value
            self.refresh()
            with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)
            self.extracted[key] = original

    def test_l5_presence_count_geometry_and_types(self):
        original = copy.deepcopy(self.rpu["vdr_dm_data"]["cmv29_metadata"])
        for mutation in ("missing", "duplicate", "count", "bool", "odd", "empty"):
            block = copy.deepcopy(original)
            area = block["ext_metadata_blocks"][0]["Level5"]
            if mutation == "missing": block["ext_metadata_blocks"] = []; block["num_ext_blocks"] = 0
            elif mutation == "duplicate": block["ext_metadata_blocks"] *= 2; block["num_ext_blocks"] = 2
            elif mutation == "count": block["num_ext_blocks"] = 2
            elif mutation == "bool": area["active_area_top_offset"] = False
            elif mutation == "odd": area["active_area_left_offset"] = 1
            else: area["active_area_bottom_offset"] = 2
            self.rpu["vdr_dm_data"]["cmv29_metadata"] = block
            self.refresh()
            with self.assertRaises(ValueError, msg=mutation): metadata.load(self.result, self.extraction)

    def test_unsupported_source_colour_declaration(self):
        self.rpu["vdr_dm_data"]["signal_full_range_flag"] = True
        self.refresh()
        with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)

    def test_only_dm_from_checked_rpu_and_type_strict_metadata(self):
        self.rpu["vdr_dm_data"]["ycc_to_rgb_coef0"] = 9000
        self.refresh()
        self.assertEqual(metadata.load(self.result, self.extraction)["source_dm"]["ycc_to_rgb_coef0"], 9000)
        self.manifest["metadata"]["disable_residual"] = 0
        self.refresh()
        with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)

    def test_contained_regular_and_bounded_json(self):
        outside = self.root / "outside.json"
        outside.write_bytes((self.extraction / "rpu.json").read_bytes())
        (self.extraction / "rpu.json").unlink()
        (self.extraction / "rpu.json").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes"): metadata.load(self.result, self.extraction)
        (self.extraction / "rpu.json").unlink()
        (self.extraction / "rpu.json").write_bytes(b" " * (metadata.LIMIT + 1))
        with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)
        if hasattr(os, "mkfifo"):
            (self.extraction / "rpu.json").unlink()
            os.mkfifo(self.extraction / "rpu.json")
            with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)

    def test_ambiguous_or_nonfinite_json_rejected(self):
        for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]'):
            (self.extraction / "rpu.json").write_bytes(payload)
            with self.assertRaises(ValueError): metadata.load(self.result, self.extraction)

    def test_configuration_creation_no_overwrite_and_explicit_policy(self):
        destination = self.root / "configuration.json"
        choices = dict(target_ycc=IDENTITY, target_lms=IDENTITY, target_offset=(0, 0, 0),
                       pq_policy="reject-outside-unit", outside_codes=[0, 0, 0], code_scale=4096)
        settings = metadata.make_configuration(self.result, self.extraction, destination, **choices)
        self.assertEqual(settings["source_association"], metadata.ASSOCIATION)
        self.assertEqual(settings["source_identity"], self.identity)
        self.assertEqual(settings["source_provenance"], metadata.load(self.result, self.extraction)["provenance"])
        original = destination.read_bytes()
        with self.assertRaises(FileExistsError): metadata.make_configuration(self.result, self.extraction, destination, **choices)
        self.assertEqual(destination.read_bytes(), original)
        for key, value in (("code_scale", 1024), ("outside_codes", [True, 0, 0]), ("pq_policy", "automatic")):
            bad = self.root / f"bad-{key}.json"
            with self.assertRaises(ValueError):
                metadata.make_configuration(self.result, self.extraction, bad, **dict(choices, **{key: value}))
            self.assertFalse(bad.exists())


if __name__ == "__main__":
    unittest.main()
