"""Additional-frame pinned evidence audit; not a fresh producer or VM run."""
import hashlib
import json
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parent
SHA = "5ab77ad763d89744f77a36c057aff2088325fce5f911225693d8e849e43fcbd3"


def replay(raw):
    if type(raw) is not bytes or len(raw) > 1024**2 or hashlib.sha256(raw).hexdigest() != SHA:
        raise ValueError("bounded original record required")
    return json.loads(raw)


class AdditionalFrameTests(unittest.TestCase):
    def raw(self):
        with (ROOT / "results/native-mmr-frame1406-vm-20261005a.json").open("rb") as f:
            return f.read(1024**2 + 1)

    def test_completed_frame_metadata_arithmetic_and_scope(self):
        d = replay(self.raw())
        self.assertEqual(d["status"], "complete")
        self.assertEqual(d["frame_label"], 1406)
        self.assertFalse(d["original_stream_pts_verified"])
        self.assertIn("software-linear", d["scaling_fixture"])
        self.assertEqual(len(d["source_sha256"]), 18)
        for name, expected in d["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        p = d["producer"]
        for key in ("decoder_metadata", "raw_rpu_exact", "el_active_planes_exact", "crc_requested"):
            self.assertTrue(p[key])
        self.assertEqual(p["frames_received"], 32)
        self.assertEqual(p["packets_sent"], 32)
        self.assertEqual(p["local_presentation_index"], 31)
        self.assertEqual(p["warning_or_error_logs"], 0)
        self.assertEqual(p["instructions_bytes"], 9216)
        self.assertFalse(p["original_pts_verified"])
        self.assertEqual(set(d["producer_packer_executable_sha256"]),
                         {"native_decoder_ingestion", "native_p010_fixture"})
        b = d["benchmark"]
        self.assertTrue(b["all_four_stages_full_frame_byte_exact"])
        self.assertEqual(b["verified_stage_values"], 49766400)
        self.assertEqual(b["verified_dispatches"], 191)
        self.assertEqual(b["counts"], [8294400, 2073600, 2073600])
        self.assertEqual(b["component_routes"], [1, 0, 0])
        self.assertEqual(b["mmr_segment_counts_by_64_128_bits"], [2, 0])
        self.assertEqual(b["verification_scope"], "untimed-full-frame-before-timing")
        self.assertEqual(b["timed_crosscheck_scope"], "last-chunk-only-external-kernels-no-lto")
        for key in ("producer_and_packer_resources", "benchmark_resources"):
            r = d[key]
            self.assertEqual(r["memory_limit_bytes"], 536870912)
            self.assertEqual(r["swap_limit_bytes"], 0)
            self.assertTrue(r["zero_swap"])
            self.assertTrue(r["zero_limit_and_oom_events"])
            self.assertGreater(r["pre_exit_peak_bytes"], 0)
            self.assertLess(r["pre_exit_peak_bytes"], r["memory_limit_bytes"])
            self.assertEqual(r["kodi_before"], "active")
            self.assertEqual(r["kodi_after"], "active")

    def test_modified_private_or_oversized_record_rejected(self):
        for raw in (self.raw() + b" ", b"[]", b" " * (1024**2 + 1)):
            with self.assertRaises(ValueError):
                replay(raw)
        d = replay(self.raw())
        d["instructions_sha256"] = "excluded"
        with self.assertRaises(ValueError):
            replay(json.dumps(d).encode())
