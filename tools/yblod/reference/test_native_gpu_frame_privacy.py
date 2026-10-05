"""Independent privacy/ordering checks using synthetic bundles and mocks only."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import native_gpu_frame_probe as probe
from native_gpu_vectors import expected_stages, width_oracle
from test_native_gpu_frame_probe import synthetic_bundle


SECRET = "PRIVATE_FILM_METADATA_DO_NOT_PUBLISH"


def private_report():
    return dict(status="complete", source_sha256={"native_gpu_probe.c": "a"*64},
        input_sha256={"manifest": "b"*64}, binary_sha256="c"*64, shader_sha256="d"*64,
        all_cpu_gates_complete=True, gpu_attempted=True,
        cases=[dict(component=channel, samples=4096, fixture_sha256="e"*64,
                    cpu_baseline_gate=True, gpu_exact=True) for channel in ("Y", "Cb", "Cr")])


class FramePrivacyTests(unittest.TestCase):
    def test_public_allowlist_discards_nested_pixels_metadata_paths_and_errors(self):
        private = private_report()
        private.update(input_manifest={"metadata": {"coefficients": [SECRET, 99901234]}},
            source_identity={"frame_id": SECRET}, argv=["/private/"+SECRET],
            error={"message": SECRET}, cgroup_before={"private": SECRET})
        for case in private["cases"]:
            case.update(cpu={"report": {"cpu_stages": [[99901234]], "rpu": SECRET}},
                        gpu={"shader_log": SECRET}, path="/private/"+SECRET)
        private["resources"] = dict(charged_peak_bytes=123, swap_bytes=0, oom_events=0,
            oom_kill_events=0, limit_events=0, argv=SECRET, file=SECRET, pid=99901234)
        result = probe.public_summary(private)
        text = json.dumps(result, sort_keys=True)
        for forbidden in (SECRET, "/private/", "99901234", "input_manifest", "cpu_stages",
                          "coefficients", "frame_id", "shader_log", '"argv"', '"error"'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(result["resources"], dict(charged_peak_bytes=123, swap_bytes=0,
            oom_events=0, oom_kill_events=0, limit_events=0))
        self.assertEqual([c["component"] for c in result["cases"]], ["Y", "Cb", "Cr"])

    def test_hash_map_keys_and_values_cannot_transport_private_data(self):
        for field in ("source_sha256", "input_sha256"):
            private = private_report()
            private[field]["/private/"+SECRET] = "a"*64
            with self.assertRaises(ValueError): probe.public_summary(private)
        for field in ("source_sha256", "input_sha256"):
            private = private_report()
            private[field][next(iter(private[field]))] = SECRET
            with self.assertRaises(ValueError): probe.public_summary(private)
        for field in ("binary_sha256", "shader_sha256"):
            private = private_report(); private[field] = SECRET
            with self.assertRaises(ValueError): probe.public_summary(private)

    def test_exact_grid_coordinates_are_content_independent(self):
        for width, height in ((3840, 2160), (1920, 1080), (65, 67), (4, 2), (1, 65)):
            nx, ny = min(64, width), min(64, height)
            expected = tuple((j*(height-1)//(ny-1) if ny>1 else 0)*width
                +(i*(width-1)//(nx-1) if nx>1 else 0) for j in range(ny) for i in range(nx))
            self.assertEqual(probe.grid_indices(width, height), expected)
            self.assertEqual(len(expected), len(set(expected)))

    def test_full_hash_detects_corruption_outside_selected_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"plane"
            values = list(range(100))
            raw = struct.pack("<100H", *values); path.write_bytes(raw)
            checksum = hashlib.sha256(raw).hexdigest()
            self.assertEqual(probe.scan_plane(directory, "plane", 100, "u16le", (0,99),
                checksum, depth=10)[0], (0, 99))
            values[50] += 1; path.write_bytes(struct.pack("<100H", *values))
            with self.assertRaises(ValueError):
                probe.scan_plane(directory, "plane", 100, "u16le", (0,99), checksum, depth=10)

    def test_all_three_cpu_gates_precede_mock_gpu_and_public_report_stays_clean(self):
        fixture, manifest, baseline = synthetic_bundle(self, mmr=True)
        vectors, _, _, _ = probe.prepare_cases(manifest, baseline, fixture.extraction)
        by_channel = {v.name:v for v in vectors}
        binary = fixture.root/"mock-binary"; binary.write_bytes(b"mock, never executed"); binary.chmod(0o700)
        events = []
        def execute(args, **kwargs):
            vector = by_channel[Path(args[-1]).stem]
            width = width_oracle(vector.mapping)
            polynomial = all(s.method=="polynomial" for c in vector.mapping.mappings for s in c.segments)
            cpu = args[1] == "--validate"
            if not cpu:
                self.assertEqual(events[:3], ["cpu-Y", "cpu-Cb", "cpu-Cr"])
            events.append(("cpu-" if cpu else "gpu-")+vector.name)
            report = dict(schema="yblod.native-gpu-probe.v2", status="validated" if cpu else "exact",
                samples=len(vector.triplets), component=vector.component, polynomial_only=polynomial,
                algorithm_supported=True, accepted=True, gpu_attempted=not cpu,
                width_report=dict(supported=True, mmr_segment_count=width["mmr_segment_count"],
                    worst_l1_bound=width["worst_l1_bound"],
                    first_unsupported_component=-1, first_unsupported_segment=-1))
            if cpu: report["cpu_stages"] = [list(row) for row in zip(*expected_stages(vector))]
            else: report.update(device_binding_verified=True, cleanup_succeeded=True,
                observed_gl_error=0, observed_egl_error=12288, fence_wait_result=37148,
                stage_mismatch_counts=[0]*4, shader_log=SECRET)
            kwargs["stdout"].write(json.dumps(report).encode())
            return subprocess.CompletedProcess(args, 0)
        with patch.object(probe.subprocess, "run", side_effect=execute):
            report = probe.run(binary, Path(probe.__file__).with_name("native_gpu_probe.comp"),
                manifest, baseline, fixture.extraction, fixture.root/"private-run", require_memory_cap=False)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(events, ["cpu-Y", "cpu-Cb", "cpu-Cr", "gpu-Y", "gpu-Cb", "gpu-Cr"])
        public = json.dumps(report)
        self.assertNotIn(SECRET, public); self.assertNotIn(str(fixture.root), public)
        self.assertNotIn("cpu_stages", public)

    def test_completed_summary_requires_consistent_exact_three_components(self):
        for mutate in (
            lambda p:p["cases"].pop(),
            lambda p:p["cases"].append(copy.deepcopy(p["cases"][0])),
            lambda p:p["cases"][0].update(gpu_exact=False),
            lambda p:p["cases"][0].update(cpu_baseline_gate=False),
            lambda p:p.update(all_cpu_gates_complete=False),
            lambda p:p.update(gpu_attempted=False),
        ):
            private = private_report(); mutate(private)
            with self.assertRaises(ValueError): probe.public_summary(private)


if __name__ == "__main__":
    unittest.main()
