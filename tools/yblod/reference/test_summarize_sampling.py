import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from summarize_sampling import GROUPS, VARIANTS, main, summarize, validate


def metrics(n, value):
    return {"samples": n, "negative": n if value < 0 else 0, "zero": n if value == 0 else 0,
            "positive": n if value > 0 else 0, "maximum_absolute_codes": abs(value) if n else 0,
            "mean_signed_codes": value if n else None, "mean_absolute_codes": abs(value) if n else None,
            "rmse_codes": abs(value) if n else None}


def fixture(frame):
    source = "synthetic fixture source\n"
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    implementations = {name: {"filename": name + ".py", "source": source, "sha256": source_hash}
                       for name in ("experiment", "geometry", "colour_conversion_and_packing")}
    helpers = {name: {"filename": name + ".py", "sha256": "9"*64} for name in
               ("diagnose_frame", "compare_output", "dvtunnel", "dvlms", "inverse_stage", "summarize_cases",
                "extract_frame", "import_rpu", "inspect_composition", "reference")}
    report = {"schema": "yblod.forward-sampling-experiment.v1", "status": "complete", "width": 128, "height": 132,
              "active_rectangle": [2, 49, 124, 132], "identity": {"frame_id": f"source:{frame}", "pts": frame, "time_base": [1, 1000]},
              "identity_basis": "synthetic fixture", "composer_report_sha256": "1"*64, "rpu_sha256": "2"*64,
              "capture_sha256": "3"*64, "source_provenance": {"output_report_sha256": "4"*64,
              "comparison_report_sha256": "5"*64, "compared_tunnel_sha256": "6"*64},
              "baseline": {"variant": "linear-left", "byte_identical": True, "verified_bytes": 128*132*3, "tunnel_sha256": "6"*64},
              "metadata": {"packets": 2, "copies_per_packet": 3, "all_crc_valid": True, "copies_identical": True},
              "held_fixed": {"policy": "direct", "matrix": "synthetic"}, "source_dm": {"frame": frame},
              "runtime": {"numpy_version": "test", "python_version": "test"}, "implementation": implementations,
              "helper_implementations": helpers, "processing_strip_rows": 32, "group_definitions": {"gradient": "fixed"}, "variants": {}}
    for variant, change in zip(VARIANTS, (0, 1, 2, -2)):
        comparisons = {}
        for name, value in (("versus_capture", 5+change), ("minus_baseline", change)):
            channels = {}
            for channel, width in (("I", 122), ("P", 61), ("T", 61)):
                n = width*83
                counts = {"all": n, "even_row": width*41, "odd_row": width*42,
                          "smooth_le_4": n//2, "intermediate_5_16": n//4, "edge_gt_16": n-n//2-n//4}
                channels[channel] = {group: metrics(counts[group], value) for group in GROUPS}
            comparisons[name] = channels
        report["variants"][variant] = {"configuration": {"schema": "yblod.chroma-geometry-experiment.v1", "variant": variant,
            "invalid_geometry_control": variant.endswith("-control"), "production_choice": False}, "comparisons": comparisons}
    return report


class SamplingSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.paths = [self.directory / f"case-{frame}.json" for frame in (1960, 2296)]
        for path, frame in zip(self.paths, (1960, 2296)):
            self.write(path, fixture(frame))

    def write(self, path, report):
        path.write_text(json.dumps(report))

    def change(self, function, index=0):
        path = self.paths[index]
        report = json.loads(path.read_text())
        function(report)
        self.write(path, report)

    def test_per_case_summary_allows_different_source_metadata_and_hashes_reports(self):
        report = summarize(self.paths)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["cases"][0]["report_sha256"], hashlib.sha256(self.paths[0].read_bytes()).hexdigest())
        variants = report["cases"][0]["variants"]
        self.assertTrue(variants["linear-bottom-control"]["invalid_geometry_control"])
        self.assertFalse(variants["cubic-left"]["invalid_geometry_control"])
        self.assertEqual(variants["cubic-left"]["error_metric_change_from_linear_baseline"]["I"]["all"]["mean_absolute_codes"], 1)
        self.assertEqual(variants["linear-bottom-control"]["processing_change_minus_linear_baseline"]["P"]["groups"]["all"]["mean_signed_codes"], -2)
        self.assertEqual(variants["cubic-left"]["versus_capture"]["T"]["even_minus_odd_mean_signed_codes"], 0)
        self.assertNotIn("ranking", report)

    def test_duplicate_case_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize([self.paths[0], self.paths[0]])

    def test_incomplete_baseline_rejected(self):
        self.change(lambda r: r["baseline"].update(verified_bytes=1))
        with self.assertRaisesRegex(ValueError, "baseline"):
            summarize(self.paths)

    def test_held_fixed_policy_difference_rejected(self):
        self.change(lambda r: r["held_fixed"].update(matrix="different"), 1)
        with self.assertRaisesRegex(ValueError, "held-fixed"):
            summarize(self.paths)

    def test_implementation_text_hash_mismatch_rejected(self):
        self.change(lambda r: r["implementation"]["geometry"].update(source="changed"))
        with self.assertRaisesRegex(ValueError, "source hash"):
            summarize(self.paths)

    def test_changed_valid_helper_hash_rejected_across_cases(self):
        self.change(lambda r: r["helper_implementations"]["diagnose_frame"].update(sha256="a"*64), 1)
        with self.assertRaisesRegex(ValueError, "helper_implementations"):
            summarize(self.paths)

    def test_changed_runtime_rejected(self):
        self.change(lambda r: r["runtime"].update(numpy_version="different"), 1)
        with self.assertRaisesRegex(ValueError, "runtime"):
            summarize(self.paths)

    def test_wrong_control_classification_rejected(self):
        self.change(lambda r: r["variants"]["linear-top-control"]["configuration"].update(invalid_geometry_control=False))
        with self.assertRaisesRegex(ValueError, "control configuration"):
            summarize(self.paths)

    def test_row_parity_is_absolute_with_odd_active_top(self):
        self.change(lambda r: r["variants"]["cubic-left"]["comparisons"]["versus_capture"]["I"].update(
            even_row=metrics(122*42, 6), odd_row=metrics(122*41, 6)))
        with self.assertRaisesRegex(ValueError, "geometry/parity"):
            summarize(self.paths)

    def test_fixed_masks_cannot_change_between_variants(self):
        def changed(report):
            groups = report["variants"]["cubic-left"]["comparisons"]["versus_capture"]["P"]
            groups["smooth_le_4"] = metrics(groups["smooth_le_4"]["samples"]+1, 6)
            groups["edge_gt_16"] = metrics(groups["edge_gt_16"]["samples"]-1, 6)
        self.change(changed)
        with self.assertRaisesRegex(ValueError, "masks differ"):
            summarize(self.paths)

    def test_metrics_must_partition_as_well_as_counts(self):
        self.change(lambda r: r["variants"]["linear-left"]["comparisons"]["versus_capture"]["I"]["even_row"].update(
            mean_signed_codes=4, mean_absolute_codes=4, rmse_codes=4))
        with self.assertRaisesRegex(ValueError, "metrics do not partition"):
            summarize(self.paths)

    def test_nonfinite_json_rejected(self):
        self.change(lambda r: r["variants"]["cubic-left"]["comparisons"]["versus_capture"]["T"]["all"].update(mean_absolute_codes=float("nan")))
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            summarize(self.paths)

    def test_empty_edge_region_has_null_metrics_and_changes(self):
        def remove_edges(report):
            for variant in report["variants"].values():
                for comparison in variant["comparisons"].values():
                    for groups in comparison.values():
                        value = groups["all"]["mean_signed_codes"]
                        groups["smooth_le_4"] = metrics(groups["all"]["samples"], value)
                        groups["intermediate_5_16"] = metrics(0, value)
                        groups["edge_gt_16"] = metrics(0, value)
        for index in range(2):
            self.change(remove_edges, index)
        report = summarize(self.paths)
        edge = report["cases"][0]["variants"]["cubic-left"]["error_metric_change_from_linear_baseline"]["I"]["edge_gt_16"]
        self.assertTrue(all(v is None for v in edge.values()))

    def test_cli_exclusive_output_and_bad_input_leaves_no_report(self):
        output = self.directory / "summary.json"
        args = ["--case", str(self.paths[0]), "--case", str(self.paths[1]), "--output", str(output)]
        main(args)
        before = output.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(output.read_bytes(), before)
        self.change(lambda r: r.update(status="incomplete"))
        second = self.directory / "bad-summary.json"
        with self.assertRaises(SystemExit):
            main(["--case", str(self.paths[0]), "--output", str(second)])
        self.assertFalse(second.exists())

    def test_empty_case_list_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            summarize([])


if __name__ == "__main__":
    unittest.main()
