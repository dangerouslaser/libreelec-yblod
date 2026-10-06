"""Audit published compiler evidence; never executes a shader."""
import hashlib
import json
from pathlib import Path
import unittest
from native_gpu_shader_inspection import parse

HERE=Path(__file__).resolve().parent/"results"
PREFIX="native-gpu-shader-inspection"

class SavedShaderInspectionTests(unittest.TestCase):
    def test_real_log_stats_exactness_and_resource_scope(self):
        raw=(HERE/(PREFIX+"-20261005a.log")).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            "065fb3ed41a3d47a67e3e2d48e793e18f2b672a5024ee531093f54a99b15c7c2")
        stats=json.loads((HERE/(PREFIX+"-stats-20261005a.json")).read_text())
        self.assertEqual(parse(raw),stats)
        self.assertEqual(stats["statistics"]["instruction_count"],1582)
        self.assertEqual(stats["statistics"]["grf_registers"],128)
        self.assertFalse(stats["statistics_are_measured_runtime"])
        self.assertFalse(stats["spill_fill_counts_are_allocator_only"])
        self.assertTrue(stats["simd16_register_allocation_failed"])
        exact_path=HERE/(PREFIX+"-exact-20261005a.json")
        exact=json.loads(exact_path.read_text())
        self.assertEqual(exact["samples"],125)
        self.assertEqual(exact["stage_mismatch_counts"],[0,0,0,0])
        self.assertTrue(exact["device_binding_verified"])
        self.assertTrue(exact["cleanup_succeeded"])
        self.assertEqual(exact["status"],"exact")
        report=json.loads((HERE/(PREFIX+"-20261005a.json")).read_text())
        self.assertEqual(report["artifact_sha256"]["gpu.json"],
            hashlib.sha256(exact_path.read_bytes()).hexdigest())
        self.assertEqual(report["artifact_sha256"]["compiler.log"],
            hashlib.sha256(raw).hexdigest())
        self.assertTrue(report["independent_cpu_gate_passed"])
        self.assertTrue(report["additional_source_pins_observed_after_job"])
        self.assertEqual(report["kodi_before"],report["kodi_after"])
        self.assertTrue(report["kodi_before"])
        for phase in ("resources_before","resources_after"):
            p=report[phase]
            self.assertEqual((p["memory.max"],p["memory.swap.max"],p["memory.swap.current"]),
                ("536870912","0","0"))
            self.assertLess(int(p["memory.peak"]),512*1024**2)
            events=dict(line.split() for line in p["memory.events"].splitlines())
            for key in ("high","max","oom","oom_kill"):
                self.assertEqual(events[key],"0")
