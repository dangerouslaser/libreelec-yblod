import copy
import json
from pathlib import Path
import tempfile
import unittest

from extract_frame import digest
from summarize_cases import main, summarize


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.direct, self.bound = self.make_case("2296")

    def make_case(self, frame):
        result = []
        for policy in ("direct", "rgb-bound-diagnostic"):
            path = self.root / (frame + "-" + policy)
            path.mkdir()
            tunnel = path / "tunnel.rgb8"
            tunnel.write_bytes(bytes(8 * 4 * 3))
            identity = {"frame_id": "a" * 64 + ":" + frame, "pts": int(frame), "time_base": [1, 1000]}
            info = dict(schema="yblod.output-reference.v1", status="complete", policy=policy,
                        identity=identity, width=8, height=4, active_rectangle=[0, 1, 8, 4],
                        target_ycc=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        target_lms=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], target_offset=[0, .5, .5],
                        composer_report_sha256="b" * 64, rpu_sha256="c" * 64,
                        chroma_expansion="test", pq_domain="test", quantization="test; no fitted offsets",
                        transport_sampling="test", source_dm={}, implementation_sha256="d" * 64,
                        numpy_version="test", stages={"unembedded_tunnel": {
                            "file": tunnel.name, "sha256": digest(tunnel), "shape": [4, 8, 3]}})
            self.write(path / "output.json", info)
            value = 4 if policy == "direct" else 2
            comparison = dict(identity=identity, policy=policy, active_rectangle=info["active_rectangle"],
                              capture_sha256="e" * 64, identity_file_sha256="f" * 64,
                              identity_basis="supplied counter", implementation_sha256="1" * 64,
                              output_report_sha256=digest(path / "output.json"),
                              metadata_first_copy_crc=[True, True], transport_matrices_equal=True,
                              channels={name: dict(samples=24 if name == "I" else 12,
                                                   mean_absolute_codes=value, rmse_codes=value + 1,
                                                   maximum_absolute_codes=20, over_sixteen_codes_percent=2)
                                        for name in ("I", "P", "T")})
            self.write(path / "sk4.json", comparison)
            result.append(path)
        return tuple(result)

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def alter(self, directory, filename, function):
        path = directory / filename
        report = json.loads(path.read_text())
        function(report)
        self.write(path, report)
        if filename == "output.json":
            self.alter(directory, "sk4.json", lambda r: r.update(output_report_sha256=digest(path)))

    def test_changes_and_no_pooling(self):
        second = self.make_case("150")
        self.alter(second[1], "sk4.json", lambda r: r["channels"]["I"].update(
            mean_absolute_codes=5, rmse_codes=6))
        report = summarize([(self.direct, self.bound), second])
        self.assertEqual(report["case_count"], 2)
        first, second = report["cases"]
        self.assertEqual(first["channels"]["I"]["change_bound_minus_direct"]["mean_absolute_codes"], -2)
        self.assertIn("mean_absolute_codes", second["channels"]["I"]["metrics_increased"])
        self.assertEqual(second["channels"]["I"]["change_bound_minus_direct"]["mean_absolute_codes"], 1)
        self.assertNotIn("channels", report)

    def test_rejects_empty_and_duplicate_cases(self):
        for cases in ([], [(self.direct, self.bound)] * 2):
            with self.assertRaises(ValueError):
                summarize(cases)

    def test_rejects_swapped_policies(self):
        with self.assertRaisesRegex(ValueError, "policy"):
            summarize([(self.bound, self.direct)])

    def test_pair_provenance_mismatch(self):
        original = json.loads((self.bound / "output.json").read_text())
        for key, value in (("composer_report_sha256", "x"), ("rpu_sha256", "x"),
                           ("target_offset", [0, 0, 0]), ("chroma_expansion", "changed"),
                           ("source_dm", {"different": True})):
            with self.subTest(key=key):
                self.write(self.bound / "output.json", original)
                self.alter(self.bound, "output.json", lambda r: r.update({key: value}))
                with self.assertRaisesRegex(ValueError, key):
                    summarize([(self.direct, self.bound)])

    def test_capture_provenance_mismatch(self):
        original = json.loads((self.bound / "sk4.json").read_text())
        for key in ("capture_sha256", "identity_file_sha256", "identity_basis", "implementation_sha256"):
            with self.subTest(key=key):
                report = copy.deepcopy(original)
                report[key] = "different"
                self.write(self.bound / "sk4.json", report)
                with self.assertRaisesRegex(ValueError, key):
                    summarize([(self.direct, self.bound)])

    def test_output_report_link_rejected(self):
        self.alter(self.bound, "sk4.json", lambda r: r.update(output_report_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "report hash"):
            summarize([(self.direct, self.bound)])

    def test_invalid_frame_identity_rejected(self):
        original = json.loads((self.bound / "output.json").read_text())
        for key, value in (("frame_id", ""), ("pts", True), ("time_base", [1, 0])):
            with self.subTest(key=key):
                self.write(self.bound / "output.json", original)
                self.alter(self.bound, "output.json", lambda r: r["identity"].update({key: value}))
                with self.assertRaisesRegex(ValueError, "frame identity"):
                    summarize([(self.direct, self.bound)])

    def test_identity_and_rectangle_rejected(self):
        for key, value in (("identity", {}), ("active_rectangle", [0, 0, 8, 4]),
                           ("transport_matrices_equal", False), ("metadata_first_copy_crc", [False, True])):
            original = json.loads((self.bound / "sk4.json").read_text())
            with self.subTest(key=key):
                self.alter(self.bound, "sk4.json", lambda r: r.update({key: value}))
                with self.assertRaises(ValueError):
                    summarize([(self.direct, self.bound)])
                self.write(self.bound / "sk4.json", original)

    def test_corrupt_tunnel_rejected(self):
        (self.bound / "tunnel.rgb8").write_bytes(bytes([1]) * 96)
        with self.assertRaisesRegex(ValueError, "tunnel integrity"):
            summarize([(self.direct, self.bound)])

    def test_tunnel_escape_rejected(self):
        self.alter(self.bound, "output.json", lambda r: r["stages"]["unembedded_tunnel"].update(file="../outside"))
        with self.assertRaisesRegex(ValueError, "tunnel integrity"):
            summarize([(self.direct, self.bound)])

    def test_invalid_samples_and_metrics_rejected(self):
        original = json.loads((self.bound / "sk4.json").read_text())
        for key, value in (("samples", 1), ("mean_absolute_codes", -1),
                           ("rmse_codes", float("nan")), ("maximum_absolute_codes", 4096),
                           ("over_sixteen_codes_percent", 101), ("rmse_codes", 0)):
            with self.subTest(key=key, value=value):
                self.write(self.bound / "sk4.json", original)
                self.alter(self.bound, "sk4.json", lambda r: r["channels"]["I"].update({key: value}))
                with self.assertRaises(ValueError):
                    summarize([(self.direct, self.bound)])

    def test_cli_and_no_overwrite(self):
        path = self.root / "summary.json"
        args = ["--case", str(self.direct), str(self.bound), "--output", str(path)]
        main(args)
        before = path.read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
