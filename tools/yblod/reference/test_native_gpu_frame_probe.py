"""Host-only tests: synthetic extraction, full CPU files and native validation."""
import hashlib
import copy
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import native_gpu_frame_probe as probe
import reference
import test_colour_metadata

ROOT = Path(__file__).resolve().parent


def synthetic_bundle(test, *, mmr=False):
    fixture = test_colour_metadata.ColourMetadataTests()
    fixture.setUp()
    test.addCleanup(fixture.doCleanups)
    if mmr:
        fixture.rpu["rpu_data_mapping"]["curves"][1] = {
            "num_pivots_minus2": 0, "pivots": [0, 1023], "mapping_idc": "MMR",
            "mmr_order_minus1": [0], "mmr_constant_int": [0], "mmr_constant": [0],
            "mmr_coef_int": [[[0, 1, 0, 0, 0, 0, 0]]],
            "mmr_coef": [[[0, 0, 0, 0, 0, 0, 0]]]}
        fixture.manifest["metadata"] = test_colour_metadata.normalize(fixture.rpu, fixture.identity)
        fixture.manifest["mmr_luma"] = "guide.u16le"
        (fixture.root / "prepared" / "guide.u16le").write_bytes(struct.pack("<2H", 123, 789))
    fixture.refresh()
    manifest_path = fixture.root / "prepared" / "frame.json"
    manifest_path.write_text(json.dumps(fixture.manifest))
    baseline = fixture.root / "baseline"
    reference.run(manifest_path, baseline)
    return fixture, manifest_path, baseline


class FrameProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("cc") is None:
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temporary.name) / "validate"
        result = subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            "-DYB_GPU_PROBE_HOST_ONLY", str(ROOT / "native_gpu_probe.c"),
            str(ROOT / "native_gpu_probe_fixture.c"), str(ROOT / "native_composer.c"),
            str(ROOT / "native_gpu_guard.c"), "-o", str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_grid_exact_endpoints_and_small_raster(self):
        self.assertEqual(probe.grid_indices(4, 2), tuple(range(8)))
        self.assertEqual(probe.grid_indices(1, 1), (0,))
        indices = probe.grid_indices(3840, 2160)
        self.assertEqual(len(indices), 4096)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[63], 3839)
        self.assertEqual(indices[-1], 3840 * 2160 - 1)
        self.assertEqual(indices[64], (2160 - 1) // 63 * 3840)
        with self.assertRaises(ValueError): probe.grid_indices(True, 10)

    def test_source_inventory_imports_without_repository_on_python_path(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in probe.SOURCES:
                shutil.copyfile(ROOT / name, Path(directory) / name)
            result = subprocess.run([sys.executable, "-I", "-c",
                f"import sys; sys.path.insert(0,{directory!r}); import native_gpu_frame_probe"],
                cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_selected_prepared_guide_and_all_twelve_stages(self):
        fixture, path, baseline = synthetic_bundle(self, mmr=True)
        vectors, stages, pins, unchanged = probe.prepare_cases(path, baseline, fixture.extraction)
        self.assertEqual(len(stages), 3)
        self.assertEqual([v.triplets[i][0] for v in vectors[1:] for i in range(2)], [123, 789, 123, 789])
        self.assertTrue(all(t[1:] == (0, 0) for t in vectors[0].triplets))
        self.assertEqual(len([k for k in pins if k.startswith(("mapped_", "residual_", "sum_", "reconstructed_"))]), 12)
        unchanged()

    def test_native_host_gate_and_no_gpu_invocation(self):
        fixture, path, baseline = synthetic_bundle(self, mmr=True)
        destination = fixture.root / "private-output"
        result = probe.run(self.binary, ROOT / "native_gpu_probe.comp", path, baseline, fixture.extraction,
                           destination, validate_only=True, require_memory_cap=False)
        self.assertEqual(result["status"], "validated")
        self.assertTrue(result["all_cpu_gates_complete"])
        self.assertFalse(result["gpu_attempted"])
        self.assertEqual([c["samples"] for c in result["cases"]], [8, 2, 2])
        self.assertTrue(all(c["cpu_baseline_gate"] for c in result["cases"]))
        public = (destination / "public-summary.json").read_text()
        for forbidden in (str(fixture.root), "cpu_stages", "frame_id", "vdr_dm_data", "coefficients"):
            self.assertNotIn(forbidden, public)
        with self.assertRaises(FileExistsError):
            probe.run(self.binary, ROOT / "native_gpu_probe.comp", path, baseline, fixture.extraction,
                      destination, validate_only=True, require_memory_cap=False)

    def test_hash_and_late_mutation_rejected(self):
        fixture, path, baseline = synthetic_bundle(self)
        _, _, _, unchanged = probe.prepare_cases(path, baseline, fixture.extraction)
        plane = path.parent / fixture.manifest["bl"]["planes"]["Y"]
        raw = bytearray(plane.read_bytes()); raw[-1] ^= 1; plane.write_bytes(raw)
        with self.assertRaises(ValueError): unchanged()
        with self.assertRaises(ValueError): probe.prepare_cases(path, baseline, fixture.extraction)

    def test_unsampled_baseline_damage_is_not_ignored(self):
        fixture, path, baseline = synthetic_bundle(self)
        report = json.loads((baseline / "report.json").read_text())
        stage = baseline / report["stages"]["sum_Cr"]["file"]
        stage.write_bytes(stage.read_bytes() + b"extra")
        with self.assertRaises(ValueError): probe.prepare_cases(path, baseline, fixture.extraction)

    def test_file_rules_and_native_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plane"
            raw = struct.pack("<3H", 0, 1024, 2); path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError): probe.scan_plane(directory, "plane", 3, "u16le", (0,), digest, depth=10)
            with self.assertRaises(ValueError): probe.scan_plane(directory, "../plane", 3, "u16le", (0,), digest)
            with self.assertRaises(ValueError): probe.scan_plane(directory, "plane", 3, "u16le", (2, 0), digest)

    def test_cpu_failure_never_reaches_gpu_or_complete_report(self):
        fixture, path, baseline = synthetic_bundle(self)
        def reject(args, **kwargs):
            self.assertEqual(args[1], "--validate")
            kwargs["stdout"].write(b'{"status":"bad-private-title"}')
            return subprocess.CompletedProcess(args, 2)
        with mock.patch.object(probe.subprocess, "run", side_effect=reject) as execution:
            result = probe.run(self.binary, ROOT / "native_gpu_probe.comp", path, baseline, fixture.extraction,
                               fixture.root / "failed", require_memory_cap=False)
        self.assertEqual(execution.call_count, 1)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["gpu_attempted"])
        self.assertNotIn("bad-private-title", json.dumps(result))

    def test_memory_cap_required_before_any_input_work(self):
        with mock.patch.object(probe.runner, "cgroup_snapshot", return_value={"status": "unavailable"}):
            with self.assertRaisesRegex(ValueError, "512MiB"):
                probe.run("missing", "missing", "missing", "missing", "missing", "missing")

    def test_success_summary_cannot_drop_gates_or_duplicate_components(self):
        fixture, path, baseline = synthetic_bundle(self)
        result = probe.run(self.binary, ROOT / "native_gpu_probe.comp", path, baseline, fixture.extraction,
                           fixture.root / "valid", validate_only=True, require_memory_cap=False)
        for change in (lambda d: d["cases"].pop(),
                       lambda d: d["cases"][1].update(component="Y"),
                       lambda d: d["cases"][0].update(cpu_baseline_gate=False),
                       lambda d: d.update(all_cpu_gates_complete=False),
                       lambda d: d.update(gpu_attempted=True),
                       lambda d: d["cases"][0].update(gpu_exact=True),
                       lambda d: d.update(status="complete")):
            malformed = copy.deepcopy(result); change(malformed)
            with self.assertRaises(ValueError): probe.public_summary(malformed)

    def test_late_resource_pressure_or_cap_change_prevents_success(self):
        fixture, path, baseline = synthetic_bundle(self)
        before = dict(status="observed", values={"memory.max": str(512 * 1024**2),
            "memory.swap.max": "0", "memory.swap.current": "0", "memory.peak": "4096",
            "memory.events": "max 0\noom 0\noom_kill 0"})
        for index, changes in enumerate(({"memory.events": "max 1\noom 0\noom_kill 0"},
                                        {"memory.swap.current": "1"}, {"memory.max": "max"})):
            after = copy.deepcopy(before); after["values"].update(changes)
            with mock.patch.object(probe.runner, "cgroup_snapshot", side_effect=[before, after]):
                result = probe.run(self.binary, ROOT / "native_gpu_probe.comp", path, baseline, fixture.extraction,
                                   fixture.root / f"resource-{index}", validate_only=True)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["all_cpu_gates_complete"])
            self.assertFalse(result["gpu_attempted"])


if __name__ == "__main__":
    unittest.main()
