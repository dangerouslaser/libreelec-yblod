"""Synthetic repeated-capture checks; no production packer expected pixels."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from transport_oracle import pixel_rgb
from extract_frame import digest

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
else:
    from compare_repeats import analyze, compare_pair, main


def crc(data):
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte*2**24
        for _ in range(8):
            value = ((value*2) ^ (0x04C11DB7 if value & 0x80000000 else 0)) & 0xFFFFFFFF
    return value


def fixture_bytes(metadata_marker=0):
    """Literal DM integers, scalar bit writer and explicit byte addresses."""
    count = 128*64
    intensity, chroma = [0xABC]*count, [0x123 if x%2 == 0 else 0x456 for x in range(count)]
    payload = bytearray(119)
    payload[2:20] = struct.pack(">9h", 8194, 799, 1681, 8194, -933, 1091, 8194, 267, -5545)
    payload[20:32] = struct.pack(">3I", 0, 134217728, 134217728)
    payload[32:50] = struct.pack(">9h", 17080, -348, -348, -348, 17080, -348, -348, -348, 17080)
    payload[100] = metadata_marker
    for packet_index, header in enumerate((64, 192)):
        body = bytes([header, 0, 0, 0, 0])+payload
        packet = body + crc(body).to_bytes(4, "big")
        for copy in range(3):
            for j in range(1024):
                pixel = packet_index*3072+copy*1024+j
                bit = (packet[j//8] // 2**(7-j%8)) % 2
                parity = (intensity[pixel].bit_count() + (chroma[pixel]//2).bit_count()) % 2
                chroma[pixel] = (chroma[pixel]//2)*2 + (bit ^ parity)
    raw = bytearray(count*3)
    for pixel, (i, c) in enumerate(zip(intensity, chroma)):
        r, g, b = pixel_rgb(i, c)
        for channel, value in enumerate((g, b, r)):
            logical = pixel*3+channel
            raw[logical//8*8+7-logical%8] = value
    return bytes(raw)


def flip_wire(raw, x, y, component, bit):
    """Explicit physical-byte location; no production encoder/decoder."""
    if component == "I":
        channel, position = (1, bit) if bit < 4 else (0, bit-4)
    else:
        channel, position = (1, bit+4) if bit < 4 else (2, bit-4)
    logical = (y*128+x)*3+channel
    physical = logical//8*8+7-logical%8
    result = bytearray(raw)
    result[physical] ^= 2**position
    return bytes(result), physical


@unittest.skipIf(np is None, "NumPy required for repeat analyzer")
class RepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fixture_bytes()
        cls.metadata_changed = fixture_bytes(1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.first, self.second = self.root/"first.rgb", self.root/"second.rgb"
        self.first.write_bytes(self.raw)
        self.second.write_bytes(self.raw)
        self.rectangle = [2, 49, 126, 64]

    def pair(self):
        return compare_pair(self.first, self.second, 128, 64, self.rectangle)

    def bundle(self, fresh=None, unstable=False):
        cycles = []
        for index in range(2):
            records = []
            for read in ("first", "second"):
                path = self.root/f"cycle-{index}-{read}.rgb"
                raw = fresh if index == 1 and fresh is not None else self.raw
                if unstable and index == 0 and read == "second":
                    raw, _ = flip_wire(raw, 7, 49, "I", 0)
                path.write_bytes(raw)
                records.append({"file": path.name, "bytes": len(raw), "sha256": digest(path)})
            cycles.append({"cycle_index": index, "buffer": {"index": index, "address_hex": "0x1234", "size": len(self.raw)},
                           "first_read": records[0], "second_read": records[1],
                           "state_after_freeze": {"pts": 555+index, "kodi_paused": True}})
        manifest = {"schema": "yblod.capture-repeat.v1", "status": "complete", "width": 128, "height": 64,
                    "cycles": cycles, "initial_state": {"untrusted_driver_pts": 12345}, "cleanup": {"done": True}}
        path = self.root/"capture.json"
        path.write_text(json.dumps(manifest))
        identity = self.root/"identity.json"
        identity.write_text(json.dumps({"source_sha256": "a"*64, "visible_frame_number": 2296, "pts_us": 95762000}))
        return path, identity

    def test_identical_bytes_guarantee_zero_decoded_changes(self):
        result = self.pair()
        self.assertTrue(result["byte_identical"])
        self.assertEqual(result["classification"], "byte_identical")
        self.assertEqual(result["changed_bytes"], 0)
        self.assertIsNone(result["first_difference_byte"])
        for channel in result["channels"].values():
            for group in channel.values():
                self.assertEqual(group["changed_samples"], 0)
                self.assertEqual(group["mean_signed_codes"], 0)
                self.assertEqual(group["mean_absolute_codes"], 0)
                self.assertEqual(group["maximum_absolute_codes"], 0)

    def test_single_literal_intensity_bit_and_absolute_odd_row(self):
        changed, position = flip_wire(self.raw, 7, 49, "I", 0)
        self.assertEqual(position, 18833)
        self.second.write_bytes(changed)
        result = self.pair()
        self.assertEqual(result["changed_bytes"], 1)
        self.assertEqual(result["first_difference_byte"], 18833)
        self.assertEqual(result["classification"], "active_picture_changed")
        groups = result["channels"]["I"]
        self.assertEqual(groups["all"]["changed_samples"], 1)
        self.assertEqual(groups["all"]["signed_decomposition"]["delta12_sum"], 1)
        self.assertEqual(groups["odd_row"]["changed_samples"], 1)
        self.assertEqual(groups["even_row"]["changed_samples"], 0)
        self.assertEqual(groups["odd_row"]["samples"], 8*124)
        self.assertEqual(groups["even_row"]["samples"], 7*124)
        self.assertEqual(result["channels"]["P"]["all"]["changed_samples"], 0)
        self.assertEqual(result["channels"]["T"]["all"]["changed_samples"], 0)

    def test_separate_p_t_slots_and_high_low_accounting(self):
        for x, wanted in ((6, "P"), (7, "T")):
            with self.subTest(channel=wanted):
                self.second.write_bytes(flip_wire(self.raw, x, 49, "C", 1)[0])
                result = self.pair()
                for channel in ("I", "P", "T"):
                    self.assertEqual(result["channels"][channel]["all"]["changed_samples"], int(channel == wanted))
                parts = result["channels"][wanted]["all"]["signed_decomposition"]
                self.assertEqual((parts["delta12_sum"], parts["weighted_high8_sum"], parts["low4_sum"]), (-2, 0, -2))

    def test_valid_metadata_only_change_is_not_picture_change(self):
        self.second.write_bytes(self.metadata_changed)
        result = self.pair()
        self.assertEqual(result["classification"], "metadata_only")
        self.assertFalse(result["active_picture_changed"])
        self.assertFalse(result["metadata"]["packet_bytes_identical"])
        self.assertGreater(result["embedded_metadata_lsb_changed_samples"], 0)
        self.assertEqual(result["nonmetadata_payload_changed_pixel_slots"], 0)

    def test_inactive_nonmetadata_bit_is_not_mislabelled_metadata_only(self):
        self.second.write_bytes(flip_wire(self.raw, 7, 48, "I", 0)[0])
        result = self.pair()
        self.assertEqual(result["classification"], "inactive_or_nonmetadata_payload_changed")
        self.assertFalse(result["active_picture_changed"])

    def test_invalid_third_metadata_copy_fails(self):
        self.second.write_bytes(flip_wire(self.raw, 1, 16, "C", 0)[0])
        with self.assertRaisesRegex(ValueError, "CRC"):
            self.pair()

    def test_full_manifest_preserves_state_and_does_not_infer_frame_from_pts(self):
        manifest, identity = self.bundle(fresh=self.metadata_changed)
        result = analyze(manifest, identity, self.rectangle)
        self.assertTrue(result["all_same_buffer_reads_byte_identical"])
        self.assertFalse(result["all_fresh_reads_byte_identical"])
        self.assertFalse(result["any_fresh_active_picture_changed"])
        self.assertEqual(result["capture_provenance"], json.loads(manifest.read_text()))
        self.assertEqual(result["identity"]["visible_frame_number"], 2296)
        self.assertEqual(result["fresh_buffer_pairs"][0]["comparison"]["classification"], "metadata_only")

    def test_unstable_reread_reported_not_hidden(self):
        manifest, identity = self.bundle(unstable=True)
        result = analyze(manifest, identity, self.rectangle)
        self.assertFalse(result["all_same_buffer_reads_byte_identical"])
        self.assertEqual(result["same_frozen_buffer_pairs"][0]["comparison"]["changed_bytes"], 1)
        self.assertIn("reread differs", result["summary_limitations"][0])

    def test_capture_claim_mismatch_rejected(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        data["cycles"][0]["same_buffer_comparison"] = {"byte_identical": False, "first_difference_offset": 0, "compared_bytes": len(self.raw)}
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "capture-side"):
            analyze(manifest, identity, self.rectangle)

    def test_optional_driver_dump_independently_compared(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        path = self.root/"driver.rgb"
        path.write_bytes(self.raw)
        data["cycles"][0]["driver_dump"] = {"file": path.name, "bytes": len(self.raw), "sha256": digest(path)}
        data["cycles"][0]["driver_vs_first_comparison"] = {"byte_identical": True, "first_difference_offset": None,
                                                            "compared_bytes": len(self.raw)}
        manifest.write_text(json.dumps(data))
        result = analyze(manifest, identity, self.rectangle)
        self.assertEqual(result["driver_dump_comparisons_available"], 1)
        self.assertTrue(result["all_available_driver_dumps_match_first_read"])
        self.assertEqual(result["driver_dump_vs_first_read_pairs"][0]["comparison"]["changed_bytes"], 0)
        self.assertEqual(result["readback_evidence"]["driver_dump_coverage"], "partial")
        self.assertEqual(result["readback_evidence"]["cycles_without_driver_dump"], [1])
        self.assertIn("stale cache", result["summary_limitations"][0])
        path.write_bytes(flip_wire(self.raw, 7, 49, "I", 0)[0])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            analyze(manifest, identity, self.rectangle)
        data["cycles"][0]["driver_dump"]["sha256"] = digest(path)
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "driver/readback claim"):
            analyze(manifest, identity, self.rectangle)

    def test_absent_driver_dump_does_not_claim_driver_validation(self):
        manifest, identity = self.bundle()
        result = analyze(manifest, identity, self.rectangle)
        self.assertEqual(result["driver_dump_comparisons_available"], 0)
        self.assertIsNone(result["all_available_driver_dumps_match_first_read"])
        evidence = result["readback_evidence"]
        self.assertEqual(evidence["driver_dump_coverage"], "none")
        self.assertEqual(evidence["cycles_without_driver_dump"], [0, 1])
        self.assertEqual(evidence["cycles_without_dma_sync_record"], [0, 1])
        self.assertFalse(evidence["dma_coherency_proven"])
        self.assertFalse(evidence["software_state_independently_attested"])
        self.assertIn("stale cache", result["summary_limitations"][0])

    def test_explicit_unverified_dma_state_is_prominent_even_for_identical_bytes(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        data["allow_unverified_dma_sync"] = True
        for cycle in data["cycles"]:
            cycle["dma_sync"] = {"status": "unverified", "driver_dump_available": False,
                                  "limitation": "identical physical reads cannot rule out stale cache data"}
        manifest.write_text(json.dumps(data))
        result = analyze(manifest, identity, self.rectangle)
        self.assertTrue(result["all_same_buffer_reads_byte_identical"])
        self.assertTrue(result["all_fresh_reads_byte_identical"])
        self.assertEqual(result["readback_evidence"]["cycles_declaring_dma_sync_unverified"], [0, 1])
        self.assertEqual(result["readback_evidence"]["cycles_without_dma_sync_record"], [])
        self.assertFalse(result["readback_evidence"]["dma_coherency_proven"])
        self.assertIn("stale cache", result["summary_limitations"][0])

    def test_driver_availability_claims_cannot_contradict_missing_evidence(self):
        manifest, identity = self.bundle()
        original = json.loads(manifest.read_text())
        for key, value in (("driver_vs_first_comparison", {"byte_identical": True}),
                           ("dma_sync", {"status": "driver_dump_observed", "driver_dump_available": True}),
                           ("dma_sync", {"status": "driver_dump_observed"})):
            data = json.loads(json.dumps(original))
            data["cycles"][0][key] = value
            manifest.write_text(json.dumps(data))
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "driver dump"):
                analyze(manifest, identity, self.rectangle)
        original["cycles"][0]["dma_sync"] = None
        manifest.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "DMA synchronization record"):
            analyze(manifest, identity, self.rectangle)

    def test_strict_dma_policy_cannot_claim_completed_missing_driver_capture(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        data["allow_unverified_dma_sync"] = False
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "strict DMA policy"):
            analyze(manifest, identity, self.rectangle)
        data["allow_unverified_dma_sync"] = "true"
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "boolean"):
            analyze(manifest, identity, self.rectangle)

    def test_matching_driver_dumps_do_not_prove_coherency(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        for index, cycle in enumerate(data["cycles"]):
            path = self.root/f"driver-{index}.rgb"
            path.write_bytes(self.raw)
            cycle["driver_dump"] = {"file": path.name, "bytes": len(self.raw), "sha256": digest(path)}
            cycle["dma_sync"] = {"status": "driver_dump_observed", "driver_dump_available": True}
        manifest.write_text(json.dumps(data))
        result = analyze(manifest, identity, self.rectangle)
        self.assertTrue(result["all_available_driver_dumps_match_first_read"])
        self.assertEqual(result["readback_evidence"]["driver_dump_coverage"], "all")
        self.assertFalse(result["readback_evidence"]["dma_coherency_proven"])
        self.assertTrue(any("instrumented" in value for value in result["summary_limitations"]))
        data["cycles"][0]["dma_sync"]["driver_dump_available"] = False
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "availability"):
            analyze(manifest, identity, self.rectangle)

    def test_hash_change_and_path_escape_rejected(self):
        manifest, identity = self.bundle()
        data = json.loads(manifest.read_text())
        path = self.root/data["cycles"][0]["first_read"]["file"]
        path.write_bytes(flip_wire(self.raw, 7, 49, "I", 0)[0])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            analyze(manifest, identity, self.rectangle)
        data["cycles"][0]["first_read"]["file"] = "../outside.rgb"
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "path"):
            analyze(manifest, identity, self.rectangle)

    def test_invalid_dimensions_rectangle_and_missing_visible_identity_rejected(self):
        manifest, identity = self.bundle()
        with self.assertRaisesRegex(ValueError, "overlap"):
            analyze(manifest, identity, [0, 0, 128, 64])
        record = json.loads(identity.read_text())
        record["source_sha256"] = "not-a-source-hash"
        identity.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "visible-frame"):
            analyze(manifest, identity, self.rectangle)

    def test_cli_writes_only_report_and_refuses_overwrite(self):
        manifest, identity = self.bundle()
        report = self.root/"comparison.json"
        args = [str(manifest), "--identity", str(identity), "--active-rectangle", *map(str, self.rectangle), "--report", str(report)]
        before = set(self.root.iterdir())
        main(args)
        self.assertEqual(set(self.root.iterdir())-before, {report})
        original = report.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
