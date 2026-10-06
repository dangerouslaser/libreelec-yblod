"""Coefficient-gated experiment arithmetic/source checks; no GPU execution."""
from pathlib import Path
import hashlib
import json
import random
import unittest

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT.parents[2] / "engine" / "experimental" if ROOT.name == "reference" else ROOT
BASE = ENGINE / "native_gpu_composer_backend.comp"
CANDIDATE = ENGINE / "native_gpu_composer_backend_coefficient_gated.comp"


def features(y, cb, cr):
    # Production's native10 domain: retain each pair/triple normalization floor.
    linear = [y * 1024, cb * 1024, cr * 1024]
    cross = [y * cb, y * cr, cb * cr, ((y * cb) * (cr * 1024)) // (1 << 20)]
    return linear + cross


def prefixes(values, coefficients, order, gated):
    total = -17 * (1 << 20)
    result = []
    for term, feature in enumerate(values):
        active = any(coefficients[degree][term] for degree in range(order))
        if gated and not active:
            result.append(total)
            continue
        # Linear squares remain their original direct native10 expression.
        square = feature * feature // (1 << 20)
        if not gated or coefficients[0][term]:
            total += coefficients[0][term] * feature
        if order >= 2 and (not gated or coefficients[1][term]):
            total += coefficients[1][term] * square
        if order >= 3 and (not gated or coefficients[2][term]):
            total += coefficients[2][term] * ((feature * square) // (1 << 20))
        result.append(total)
    return result


class CoefficientGatedTests(unittest.TestCase):
    def test_saved_abba_scope_source_pins_and_resources(self):
        report_path = (ROOT / "results" / "native-coefficient-gated-abba-20261006.json"
                       if ROOT.name == "reference" else ROOT / "NATIVE_COEFFICIENT_GATED_RESULTS.json")
        report = json.loads(report_path.read_text())
        self.assertEqual(report["schema"], "yblod.coefficient-gated-shader-abba.v1")
        self.assertFalse(report["production_adopted"])
        self.assertIn("No established speed gain", report["conclusion"])
        self.assertEqual(report["geometry"], [3840, 2160])
        self.assertEqual(report["order"], ["A1", "B1", "B2", "A2"])
        self.assertEqual([run["id"] for run in report["runs"]], report["order"])
        self.assertEqual(report["failed_attempts"], 0)
        self.assertEqual(report["retries"], 0)
        for path, key in ((BASE, "baseline_shader_sha256"), (CANDIDATE, "candidate_shader_sha256")):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), report[key])
        expected = {"cpu_stage_values": 49766400, "gpu_exact_reconstructed_values": 12441600,
                    "full_frame_exact": True, "cleanup_succeeded": True,
                    "input_artifact_runtime_kodi_identity_unchanged": True,
                    "memory_limit_bytes": 536870912, "swap_bytes": 0,
                    "memory_events_all_zero": True, "cpu_quota_us": 100000,
                    "cpu_period_us": 100000, "nr_throttled_delta": 0,
                    "throttled_usec_delta": 0, "deadline_seconds": 60, "warmups": 1}
        self.assertEqual(report["each_run"], expected)
        wall = [[67153901, 67002549, 66751091], [55295534, 67220297, 67075450],
                [67788093, 80993975, 68034560], [32898196, 32739383, 32817658]]
        for run, samples in zip(report["runs"], wall):
            self.assertEqual(run["wall_ns"], samples)
            self.assertEqual(len(run["cpu_ns"]), 3)
            self.assertTrue(all(0 < n <= 5000000000 for n in run["wall_ns"] + run["cpu_ns"]))
            self.assertLess(run["memory_peak_snapshot_bytes"], 536870912)
            self.assertGreater(run["wrapper_window_cpu_usage_delta_us"], 0)
            for key in ("act_freq_before_after_mhz", "cur_freq_before_after_mhz"):
                self.assertEqual(len(run[key]), 2)
                self.assertTrue(all(isinstance(n, int) and n >= 0 for n in run[key]))
        serialized = report_path.read_text()
        for private_marker in ("/storage/", "/home/", "/private/", "instructions.bin", "scaled1.p010"):
            self.assertNotIn(private_marker, serialized)

    def test_every_zero_degree_pattern_each_term_and_order(self):
        values = features(1023, 511, 1)
        for order in (1, 2, 3):
            for term in range(7):
                for mask in range(1 << order):
                    coefficients = [[0] * 7 for _ in range(3)]
                    for degree in range(order):
                        coefficients[degree][term] = (-31 if degree & 1 else 19) if mask & (1 << degree) else 0
                    self.assertEqual(prefixes(values, coefficients, order, False),
                                     prefixes(values, coefficients, order, True))

    def test_seeded_all_prefixes_with_signed_coefficients(self):
        rng = random.Random(62936)
        anchors = [(0, 0, 0), (1023, 1023, 1023), (1, 1023, 511), (1023, 1, 1023)]
        samples = anchors + [tuple(rng.randrange(1024) for _ in range(3)) for _ in range(1000)]
        for sample in samples:
            for order in (1, 2, 3):
                coefficients = [[rng.choice((0, 0, 0, -1024, -1, 1, 1024)) for _ in range(7)] for _ in range(3)]
                reference = prefixes(features(*sample), coefficients, order, False)
                candidate = prefixes(features(*sample), coefficients, order, True)
                self.assertEqual(reference, candidate)
                self.assertTrue(all(-(1 << 63) <= value < (1 << 63) for value in reference))

    def test_sampling_polynomial_nlq_output_and_guards_unchanged(self):
        base, candidate = BASE.read_text(), CANDIDATE.read_text()
        self.assertEqual(base.split("// Preserve each original feature's floor.")[0],
                         candidate.split("// Experimental coefficient-gated variant.")[0])
        start = "void main()"
        stop = "    } else {\n        int depth=int(m[4]);"
        self.assertEqual(base.split(start)[1].split(stop)[0], candidate.split(start)[1].split(stop)[0])
        tail = "    int64_t mapped=bound("
        self.assertEqual(base.split(tail)[1], candidate.split(tail)[1])
        self.assertNotIn("float", candidate.split("bool feature_active")[1].split("void main()")[0])
        for term in range(7):
            self.assertIn(f"if(feature_active(offset,order,{term}))", candidate)
        self.assertIn("floor_power_two(feature*feature,20)", candidate)
        self.assertIn("floor_power_two(feature*squared,20)", candidate)
        self.assertIn("floor_power_two((y*cb*pair_scale)*(cr*linear_scale),20)", candidate)


if __name__ == "__main__":
    unittest.main()
