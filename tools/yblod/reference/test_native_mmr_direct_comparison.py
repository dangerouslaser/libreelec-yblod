"""Audit pinned public evidence; not a new VM performance run."""
import hashlib
import json
from pathlib import Path
import statistics
import unittest

ROOT = Path(__file__).resolve().parent
REPORT_SHA = "cd235a492522d2b47c13755839db6b3d1308d85ceb08b77e3e1e9fdb9c0489d7"


def replay(raw):
    if type(raw) is not bytes or len(raw) > 1024**2:
        raise ValueError("bounded bytes required")
    if hashlib.sha256(raw).hexdigest() != REPORT_SHA:
        raise ValueError("checkpoint changed")
    return json.loads(raw)


class DirectComparisonTests(unittest.TestCase):
    def raw(self):
        with (ROOT / "results/native-mmr-direct-comparison-vm-20261005a.json").open("rb") as stream:
            return stream.read(1024**2 + 1)

    def test_source_identity_exactness_and_resource_evidence(self):
        d = replay(self.raw())
        self.assertEqual(d["schema"], "yblod.native-mmr-direct-comparison.v1")
        self.assertEqual(d["status"], "complete")
        self.assertEqual(len(d["source_sha256"]), 15)
        for name, expected in d["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        self.assertEqual([r["backend"] for r in d["runs"]],
                         ["baseline", "candidate", "candidate", "baseline", "baseline", "candidate"])
        for index, r in enumerate(d["runs"], 1):
            self.assertEqual(r["index"], index)
            b = r["benchmark"]
            self.assertEqual(b["verified_stage_values"], 49766400)
            self.assertEqual(b["verified_dispatches"], 191)
            self.assertEqual(b["counts"], [8294400, 2073600, 2073600])
            self.assertTrue(b["all_four_stages_full_frame_byte_exact"])
            self.assertEqual(b["verification_scope"], "untimed-full-frame-before-timing")
            self.assertEqual(b["timed_crosscheck_scope"], "last-chunk-only-external-kernels-no-lto")
            self.assertTrue(b["preparation_and_teardown_included"])
            self.assertEqual(b["component_routes"], [1, 0, 0])
            self.assertEqual(b["mmr_segment_counts_by_64_128_bits"], [2, 0])
            self.assertEqual(b["paired_repeats"], 3)
            self.assertEqual(b["plan_bytes"], 36848 if r["backend"] == "baseline" else 46064)
            for backend in ("reference", "mmr"):
                for values in b[backend].values():
                    self.assertEqual(len(values), 3)
                    self.assertTrue(all(type(v) is int and v >= 0 for v in values))
                for clock in ("wall", "cpu"):
                    self.assertTrue(all(p <= t for p, t in zip(
                        b[backend]["preparation_" + clock + "_ns"], b[backend][clock + "_ns"])))
            resources = r["resources"]
            self.assertEqual(resources["memory_max_bytes"], 536870912)
            self.assertGreater(resources["pre_exit_peak_bytes"], 0)
            self.assertLessEqual(resources["pre_exit_peak_bytes"], resources["memory_max_bytes"])
            for key in ("swap_max_bytes", "swap_current_bytes", "high", "max", "oom", "oom_kill"):
                self.assertEqual(resources[key], 0)
            self.assertEqual(resources["kodi_before"], "active")
            self.assertEqual(resources["kodi_after"], "active")

    def test_recompute_pairs_and_pooled_medians(self):
        d = replay(self.raw())
        for i, pair in enumerate(d["pairs"]):
            runs = d["runs"][2*i:2*i+2]
            self.assertEqual(pair["order"], [r["backend"] for r in runs])
            medians = {r["backend"]: statistics.median(r["benchmark"]["mmr"]["wall_ns"]) for r in runs}
            for backend in ("baseline", "candidate"):
                self.assertEqual(pair[backend + "_median_wall_ns"], medians[backend])
            self.assertAlmostEqual(pair["reduction_fraction"], 1-medians["candidate"]/medians["baseline"])
            self.assertLess(medians["candidate"], medians["baseline"])
        medians = {backend: statistics.median([
            n for r in d["runs"] if r["backend"] == backend
            for n in r["benchmark"]["mmr"]["wall_ns"]]) for backend in ("baseline", "candidate")}
        for backend in ("baseline", "candidate"):
            self.assertEqual(d["summary"][backend + "_pooled_median_wall_ns"], medians[backend])
        self.assertAlmostEqual(d["summary"]["reduction_fraction"], 1-medians["candidate"]/medians["baseline"])

    def test_tampered_or_oversized_evidence_rejected(self):
        for raw in (self.raw() + b" ", b"[]", b" " * (1024**2 + 1)):
            with self.assertRaises(ValueError):
                replay(raw)
        d = replay(self.raw())
        d["private_paths"] = "excluded"
        with self.assertRaises(ValueError):
            replay(json.dumps(d).encode())
