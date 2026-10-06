"""Saved public numeric evidence; no GPU or private inputs."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent

class OutputTransferResultsTests(unittest.TestCase):
    def test_saved_checkpoint(self):
        raw = (HERE / "OUTPUT_TRANSFER_ABBA_RESULTS.json").read_bytes()
        self.assertLess(len(raw), 1024**2)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            "2cbc78e48d0192075cdfe97206c2fd9f98e4e86cb841d974df1f7c737c98614c")
        data = json.loads(raw)
        self.assertEqual(set(data), {"schema", "claims", "provenance", "runs"})
        self.assertFalse(data["claims"]["performance_gain_established"])
        self.assertFalse(data["claims"]["production_playback_tested"])
        root = next(p for p in HERE.parents if (p / "engine").is_dir())
        for name, pin in data["provenance"]["source_sha256"].items():
            self.assertTrue(name.startswith("engine/"))
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), pin)
        self.assertEqual(len(data["runs"]), 8)
        self.assertEqual([r["variant"] for r in data["runs"]],
            ["baseline", "output", "output", "baseline"] * 2)
        for run in data["runs"]:
            r = run["result"]
            self.assertEqual(r["status"], "complete")
            self.assertTrue(r["full_frame_gpu_exact"])
            self.assertEqual(r["gpu_verified_stage_values"], 49766400)
            self.assertEqual(r["gpu_verified_dispatches"], 48)
            self.assertFalse(r["whole_frame_resident"])
            self.assertFalse(r["dispatch_timing_is_device_kernel_time"])
            self.assertEqual(len(r["wall_ns"]), 3)
            if run["variant"] == "output":
                self.assertEqual((r["warm_output_sentinel_uploads"],
                    r["warm_readbacks_per_pass"], r["warm_readback_bytes"]),
                    (0, 1, 671744))
            resource = run["resources"]
            self.assertTrue(resource["files_and_runtime_unchanged"])
            self.assertEqual(resource["kodi_after"], "active")
            for phase in ("before", "after"):
                p = resource[phase]
                self.assertEqual(p["memory.max"], "536870912")
                self.assertEqual(p["memory.swap.max"], "0")
                self.assertEqual(p["memory.swap.current"], "0")
                events = dict(line.split() for line in p["memory.events"].splitlines())
                for key in ("high", "max", "oom", "oom_kill"):
                    self.assertEqual(events[key], "0")
