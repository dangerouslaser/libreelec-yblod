"""Small stdlib integrity/orchestration tests; no movie decoding or device I/O."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preparation_experiment as experiment
from extract_frame import digest


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_layer_policy_commands_preserve_legacy_default(self):
        argv = experiment.prepare_command("source", "target", "linear", "linear")
        self.assertEqual(argv[2:], ["source", "target", "--phase-filter", "linear"])
        for _, bl, el in experiment.CASES[1:]:
            argv = experiment.prepare_command("source", "target", bl, el)
            self.assertEqual(argv[-4:], ["--bl-phase-filter", bl, "--el-phase-filter", el])
        with self.assertRaises(ValueError):
            experiment.prepare_command("source", "target", "cubic", "linear")

    def test_effective_legacy_mixed_and_invalid_filters(self):
        self.assertEqual(experiment.effective_filters({"phase_filter": "linear"}), {"bl": "linear", "el": "linear"})
        mixed = {"phase_filter": None, "phase_filters": {"bl": "cubic128", "el": "linear"}}
        self.assertEqual(experiment.effective_filters(mixed), mixed["phase_filters"])
        for value in ({"phase_filter": "other"}, {"phase_filters": {"bl": "linear"}}):
            with self.assertRaises(ValueError):
                experiment.effective_filters(value)

    def test_stage_hash_size_and_escape_checks(self):
        path = self.root / "plane"
        path.write_bytes(b"01234567")
        record = {"file": "plane", "sha256": digest(path)}
        self.assertEqual(experiment.stage_file(self.root, record, 8), path)
        for wrong, size in ((dict(record, sha256="0"*64), 8), (record, 7), (dict(record, file=str(path)), 8)):
            with self.assertRaises(ValueError):
                experiment.stage_file(self.root, wrong, size)
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(ValueError):
            experiment.stage_file(nested, dict(record, file="../plane"), 8)

    def test_byte_comparison_includes_full_tail_and_inactive_bytes(self):
        first, second = self.root / "a", self.root / "b"
        first.write_bytes(b"0123456789")
        second.write_bytes(first.read_bytes())
        with patch.object(experiment, "CHUNK_BYTES", 4):
            self.assertEqual(experiment.byte_identical(first, second), 10)
            for bad in (b"X123456789", b"012345678X", b"012345678"):
                second.write_bytes(bad)
                with self.assertRaisesRegex(ValueError, "byte mismatch"):
                    experiment.byte_identical(first, second)
        with self.assertRaisesRegex(ValueError, "stage set"):
            experiment.equal_bundles({"a": first}, {"b": second})

    def test_child_is_checked_serial_and_logs_not_piped(self):
        log = self.root / "worker.log"
        with patch.object(experiment.subprocess, "run") as child:
            experiment.run_stage(["python", "worker.py"], log)
        self.assertEqual(child.call_args.kwargs["check"], True)
        self.assertEqual(child.call_args.kwargs["stderr"], subprocess.STDOUT)
        self.assertNotEqual(child.call_args.kwargs["stdout"], subprocess.PIPE)
        with self.assertRaises(FileExistsError):
            experiment.run_stage(["python", "worker.py"], log)

    def make_stage_maps(self):
        prep_names = ["bl_Y", "bl_Cb", "bl_Cr", "bl_Cb_phase", "bl_Cr_phase", "el_Y", "el_Cb", "el_Cr",
                      "el_Y_vertical", "el_Cb_vertical", "el_Cr_vertical", "el_Cb_phase", "el_Cr_phase",
                      "scaler_input_Y", "scaler_input_Cb", "scaler_input_Cr", "mmr_luma"]
        composed_names = [kind+"_"+c for kind in ("mapped", "residual", "sum", "reconstructed") for c in experiment.CHANNELS]
        maps = {}
        for case in ("saved", *[c[0] for c in experiment.CASES]):
            folder = self.root / case
            folder.mkdir()
            prep, composed = {}, {}
            for target, names in ((prep, prep_names), (composed, composed_names)):
                for name in names:
                    path = folder / name
                    path.write_bytes((name+"-data").encode())
                    target[name] = path
            maps[case] = prep, composed
        return maps

    def test_factorial_stage_isolation_and_nonadditive_output(self):
        maps = self.make_stage_maps()
        base_p, base_c = maps["saved"]
        for name, _, _ in experiment.CASES:
            p, c = maps[name]
            experiment.factorial_controls(name, p, c, base_p, base_c, {key: value[1] for key, value in maps.items()})
        for case, area, stage in (("cubic-bl-only", 0, "el_Cb"), ("cubic-bl-only", 1, "residual_Cb"),
                                  ("cubic-el-only", 0, "bl_Cb"), ("cubic-el-only", 1, "mapped_Cb"),
                                  ("cubic-both", 1, "mapped_Cb"), ("cubic-both", 1, "reconstructed_Y")):
            with self.subTest(case=case, stage=stage):
                path = maps[case][area][stage]
                original = path.read_bytes()
                path.write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    experiment.factorial_controls(case, *maps[case], base_p, base_c, {key: value[1] for key, value in maps.items()})
                path.write_bytes(original)

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "NumPy required for strip worker")
    def test_delta_uses_rgb_not_ce_and_global_row_and_chroma_parity(self):
        import numpy as np
        first, second = self.root / "base", self.root / "candidate"
        first.mkdir()
        second.mkdir()
        a = np.empty((6, 8, 3), dtype=np.uint8)
        a[:] = [10, 20, 5]
        b = a.copy()
        b[0, 0, 0] += 7  # Outside the active rectangle, never scored.
        b[1, 3, 0] += 1  # T high byte at odd stored x: +16 on odd global row.
        b[2, 2, 1] += 1  # I high byte: +16 on even global row.
        b[4, 2, 2] += 16  # P low nibble in B's upper half: +1.
        for directory, values in ((first, a), (second, b)):
            (directory / "tunnel.rgb8").write_bytes(values.tobytes())
        info = {key: "fixed" for key in experiment.FIXED_OUTPUT}
        info.update(width=8, height=6, active_rectangle=[2, 1, 6, 6],
                    stages={"unembedded_tunnel": {"file": "tunnel.rgb8"}})
        with patch.object(experiment, "checked", return_value=(info, {}, {})), patch.object(experiment, "STRIP_ROWS", 2):
            report = experiment.tunnel_delta(first, second)
        for name, expected_sum, count in (("I", 16, 20), ("P", 1, 10), ("T", 16, 10)):
            groups = report["channels"][name]
            self.assertEqual(groups["all"]["samples"], count)
            self.assertAlmostEqual(groups["all"]["mean_signed_codes"]*count, expected_sum)
        self.assertEqual(report["channels"]["T"]["even_row"]["mean_signed_codes"], 0)
        self.assertAlmostEqual(report["channels"]["T"]["odd_row"]["mean_signed_codes"]*6, 16)


class OrchestrationTests(unittest.TestCase):
    setUp = IntegrityTests.setUp
    make_stage_maps = IntegrityTests.make_stage_maps
    def fixture(self):
        self.maps = self.make_stage_maps()
        self.extraction = self.root / "extraction"
        self.extraction.mkdir()
        self.dm = {"test": "metadata"}
        (self.extraction / "rpu.json").write_text(json.dumps({"vdr_dm_data": self.dm}))
        self.identity = {"frame_id": "a"*64+":1943", "pts": 1943, "time_base": [1, 24]}
        self.capture, self.identity_file = self.root / "capture.rgb", self.root / "identity.json"
        self.capture.write_bytes(b"capture")
        self.identity_file.write_text("{}")
        self.output = self.root / "experiment"
        self.info = {key: "fixed" for key in experiment.FIXED_OUTPUT}
        self.info.update(identity=self.identity, width=8, height=8, active_rectangle=[0, 2, 8, 8], source_dm=self.dm,
                         rpu_sha256=digest(self.extraction / "rpu.json"))
        self.comparison = {"identity": self.identity, "capture_sha256": digest(self.capture),
                           "identity_file_sha256": digest(self.identity_file), "identity_basis": "supplied visible frame",
                           "implementation_sha256": "comparison", "channels": {"I": {"samples": 48}}}
        details = {key: "unchanged" for key in ("source_extraction_sha256", "source_composition_sha256",
                   "source_verification_sha256", "source_plane_sha256", "native_chroma_locations", "output_chroma_location",
                   "specification_pdf_sha256", "geometry_assumption")}
        details.update(phase_filter="linear", preparer_sha256="prepare", numpy_version="test", operations={})
        self.manifest = {"schema": "schema", "width": 8, "height": 8, "format": "420", "transfer": "pq",
                         "chroma_location": "left", "metadata": {}, "preparation_details": details}
        self.calls = []
        def case_for(path):
            return next((name for name, _, _ in experiment.CASES if name in Path(path).parts), "saved")
        def prepared(path):
            case = case_for(path)
            manifest = copy.deepcopy(self.manifest)
            if case != "saved":
                _, bl, el = next(item for item in experiment.CASES if item[0] == case)
                manifest["preparation_details"]["phase_filters"] = {"bl": bl, "el": el}
            return manifest, self.maps[case][0]
        def composer(path, *_):
            return {"implementation_sha256": "composer"}, self.maps[case_for(path)][1]
        def output_bundle(path, *_):
            return copy.deepcopy(self.info), copy.deepcopy(self.comparison), {"test": "provenance"}, {
                "unembedded_tunnel": self.maps[case_for(path)][1]["reconstructed_Y"]}
        def worker(argv, log):
            script = Path(argv[1]).name
            self.calls.append(script)
            if getattr(self, "fail_on", None) == script:
                raise subprocess.CalledProcessError(1, argv)
            if script == "prepare_frame.py":
                folder, filename, value = Path(argv[3]), "frame.json", {}
            elif script == "reference.py":
                folder, filename, value = Path(argv[3]), "report.json", {}
            elif script == "output_frame.py":
                folder, filename, value = Path(argv[4]), "output.json", {}
            else:
                folder, filename = Path(argv[-1]).parent, Path(argv[-1]).name
                value = {}
                if script == "transport_precision.py":
                    value = {"status": "complete", "identity": self.identity, "capture_sha256": self.comparison["capture_sha256"],
                             "active_rectangle": self.info["active_rectangle"],
                             "metadata": {"packets": 2, "copies_per_packet": 3, "all_crc_valid": True, "copies_identical": True},
                             "implementation": {"sha256": "precision"}, "helper_implementations": {}, "runtime": {},
                             "even_minus_odd_signed_mean_gaps": {}}
            folder.mkdir(parents=True, exist_ok=True)
            (folder / filename).write_text(json.dumps(value))
        for name, replacement in (("prepared_bundle", prepared), ("composer_bundle", composer),
                                  ("output_bundle", output_bundle), ("run_stage", worker),
                                  ("source_binding", lambda *_: self.identity)):
            patcher = patch.object(experiment, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.args = (self.extraction, self.root / "saved", self.root / "saved", self.root / "saved",
                     self.capture, self.identity_file, self.output, 1943)

    def test_four_cases_all_stages_sequential_and_completion_last(self):
        self.fixture()
        report = experiment.experiment(*self.args)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(self.calls, ["prepare_frame.py", "reference.py", "output_frame.py", "compare_output.py",
                                     "transport_precision.py", "preparation_experiment.py"]*4)
        self.assertEqual(set(report["variants"]), {c[0] for c in experiment.CASES})
        self.assertTrue((self.output / "experiment.json").is_file())

    def test_stage_failure_never_writes_final_report(self):
        self.fixture()
        self.fail_on = "reference.py"
        with self.assertRaises(subprocess.CalledProcessError):
            experiment.experiment(*self.args)
        self.assertEqual(self.calls, ["prepare_frame.py", "reference.py"])
        self.assertFalse((self.output / "experiment.json").exists())

    def test_invalid_baseline_rejected_before_children_or_output(self):
        self.fixture()
        self.manifest["preparation_details"]["phase_filter"] = "cubic128"
        with self.assertRaisesRegex(ValueError, "linear preparation"):
            experiment.experiment(*self.args)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_baseline_changed_border_or_plane_rejected(self):
        self.fixture()
        self.maps["linear-both"][0]["bl_Cb_phase"].write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "baseline byte mismatch"):
            experiment.experiment(*self.args)
        self.assertEqual(self.calls, ["prepare_frame.py"])
        self.assertFalse((self.output / "experiment.json").exists())

    def test_runtime_drift_rejected_before_completion(self):
        self.fixture()
        original = experiment.prepared_bundle
        def changed(path):
            manifest, files = original(path)
            if "cubic-el-only" in Path(path).parts:
                manifest["preparation_details"]["numpy_version"] = "changed"
            return manifest, files
        with patch.object(experiment, "prepared_bundle", changed):
            with self.assertRaisesRegex(ValueError, "runtime changed"):
                experiment.experiment(*self.args)
        self.assertFalse((self.output / "experiment.json").exists())

    def test_wrapper_source_drift_rejected_before_workers(self):
        self.fixture()
        calls = []
        def hashing(path):
            if Path(path).name == "preparation_experiment.py":
                calls.append(path)
                return "initial" if len(calls) == 1 else "changed"
            return digest(path)
        with patch.object(experiment, "digest", hashing):
            with self.assertRaisesRegex(ValueError, "wrapper changed"):
                experiment.experiment(*self.args)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.output / "experiment.json").exists())


if __name__ == "__main__":
    unittest.main()
