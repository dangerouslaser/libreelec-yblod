"""Pinned aggregate audit, not a fresh VM speed measurement."""
import hashlib
import json
from pathlib import Path
import statistics
import unittest
ROOT = Path(__file__).resolve().parent
REPORT_SHA = "f5929ac99b31670d5b9fa1ae079ccc1a9f023e195fd5abdb14ddb2e8939f6d39"


def replay(raw):
    if type(raw) is not bytes or len(raw) > 1024**2 or hashlib.sha256(raw).hexdigest() != REPORT_SHA:
        raise ValueError("bounded original checkpoint required")
    return json.loads(raw)


class TermsResultsTests(unittest.TestCase):
    def raw(self):
        with (ROOT / "results/native-mmr-terms-comparison-vm-20261005a.json").open("rb") as f:
            return f.read(1024**2 + 1)

    def test_source_gates_resources_and_recomputed_statistics(self):
        d = replay(self.raw())
        self.assertEqual(d["status"], "complete")
        self.assertEqual(len(d["source_sha256"]), 16)
        for name, expected in d["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        self.assertEqual(hashlib.sha256((ROOT / "test_native_mmr_terms_composer.py").read_bytes()).hexdigest(),
                         d["independent_test_sha256"])
        self.assertEqual([r["backend"] for r in d["runs"]],
                         ["prepared", "terms", "terms", "prepared", "prepared", "terms"])
        for r in d["runs"]:
            b = r["benchmark"]
            self.assertTrue(b["all_four_stages_full_frame_byte_exact"])
            self.assertEqual(b["verified_stage_values"], 49766400)
            self.assertEqual(b["verified_dispatches"], 191)
            self.assertEqual(b["counts"], [8294400, 2073600, 2073600])
            self.assertEqual(b["verification_scope"], "untimed-full-frame-before-timing")
            self.assertEqual(b["timed_crosscheck_scope"], "last-chunk-only-external-kernels-no-lto")
            self.assertTrue(b["preparation_and_teardown_included"])
            self.assertEqual(b["plan_bytes"], 46064)
            self.assertEqual(b["paired_repeats"], 3)
            resources = r["resources"]
            self.assertGreater(resources["pre_exit_peak_bytes"], 0)
            self.assertLess(resources["pre_exit_peak_bytes"], 536870912)
            for key in ("high", "max", "oom", "oom_kill", "swap_current_bytes"):
                self.assertEqual(resources[key], 0)
            self.assertEqual(resources["kodi_before"], "active")
            self.assertEqual(resources["kodi_after"], "active")
        for i, pair in enumerate(d["pairs"]):
            runs = d["runs"][2*i:2*i+2]
            medians = {r["backend"]: statistics.median(r["benchmark"]["mmr"]["wall_ns"]) for r in runs}
            self.assertEqual(pair["order"], [r["backend"] for r in runs])
            for backend in ("prepared", "terms"):
                self.assertEqual(pair[backend + "_median_wall_ns"], medians[backend])
            self.assertAlmostEqual(pair["reduction_fraction"], 1-medians["terms"]/medians["prepared"])
            self.assertLess(medians["terms"], medians["prepared"])
        pooled = {backend: statistics.median([v for r in d["runs"] if r["backend"] == backend
                    for v in r["benchmark"]["mmr"]["wall_ns"]]) for backend in ("prepared", "terms")}
        for backend in ("prepared", "terms"):
            self.assertEqual(d["summary"][backend + "_pooled_median_wall_ns"], pooled[backend])
        self.assertAlmostEqual(d["summary"]["reduction_fraction"], 1-pooled["terms"]/pooled["prepared"])

    def test_changed_extra_private_and_oversized_evidence_rejected(self):
        for raw in (self.raw() + b" ", b"[]", b" " * (1024**2 + 1)):
            with self.assertRaises(ValueError):
                replay(raw)
        d = replay(self.raw())
        d["private_paths"] = "not allowed"
        with self.assertRaises(ValueError):
            replay(json.dumps(d).encode())
