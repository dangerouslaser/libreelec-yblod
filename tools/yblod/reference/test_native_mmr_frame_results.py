"""Pinned public checkpoint replay, not another VM benchmark run."""
import hashlib
import json
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parent
REPORT_SHA = "2f4274051d6e04a5cf05ccf562bea28ad14063010a7dd5c373eee6baf19a7380"
SOURCES = ["native_scaled_frame_mmr_benchmark.c","native_mmr_composer.c","native_mmr_composer.h","native_scaled_surface.c","native_scaled_surface.h","native_decoder_frame_bridge.c","native_decoder_frame_bridge.h","native_dovi_adapter.h","native_integration_probe.c","native_integration_probe.h","native_composer.c","native_composer.h","native_sampling_probe.c","native_sampling_probe.h"]

def replay(raw):
    if type(raw) is not bytes or len(raw) > 1024**2:
        raise ValueError("bounded bytes required")
    if hashlib.sha256(raw).hexdigest() != REPORT_SHA:
        raise ValueError("checkpoint bytes changed")
    return json.loads(raw)

class MMRResultsTests(unittest.TestCase):
    def raw(self):
        with (ROOT / "results/native-mmr-frame-vm-20261005a.json").open("rb") as stream:
            return stream.read(1024**2 + 1)

    def test_checkpoint_and_all_executed_source_pins(self):
        d = replay(self.raw())
        self.assertEqual(d["schema"], "yblod.native-mmr-frame-results.v1")
        self.assertEqual(d["status"], "complete")
        self.assertEqual(set(d["source_sha256"]), set(SOURCES))
        for name, expected in d["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        b = d["benchmark"]
        self.assertEqual(b["verified_stage_values"], 49766400)
        self.assertEqual(b["verified_dispatches"], 191)
        self.assertEqual(b["counts"], [8294400, 2073600, 2073600])
        self.assertEqual(b["mmr_segment_counts_by_64_128_bits"], [2, 0])
        self.assertTrue(b["all_four_stages_full_frame_byte_exact"])
        self.assertEqual(b["verification_scope"], "untimed-full-frame-before-timing")
        self.assertTrue(b["preparation_and_teardown_included"])
        self.assertEqual(d["resources"]["peak_snapshot_after_bytes"], 57659392)
        self.assertFalse(d["scope"]["private_pixels_metadata_input_hashes_paths_published"])
        self.assertFalse(d["scope"]["production_playback_changed"])

    def test_changed_claims_extra_private_data_and_oversized_input_rejected(self):
        d = replay(self.raw())
        for key in ("metadata", "private_paths", "input_sha256"):
            altered = dict(d); altered[key] = "not-public"
            with self.subTest(key=key), self.assertRaises(ValueError):
                replay(json.dumps(altered).encode())
        d["benchmark"]["mmr"]["wall_ns"][0] = 1
        with self.assertRaises(ValueError):
            replay(json.dumps(d).encode())
        for raw in (b"[]", b'{"x":1,"x":2}', b" " * (1024**2 + 1)):
            with self.assertRaises(ValueError):
                replay(raw)

