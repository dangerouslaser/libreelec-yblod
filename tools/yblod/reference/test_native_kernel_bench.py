import ctypes as C
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import native_kernel_bench as bench
import native_stage as adapter


class NativeKernelBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.library = bench.build(Path(cls.temporary.name)/"build")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_cases_repeated_exact_and_timed(self):
        report = bench.run(self.library, count=33, iterations=2, repeats=2)
        self.assertEqual(report["timed_component_samples"], 660)
        self.assertEqual(set(report["cases"]), set(bench.CASES))
        for case, result in report["cases"].items():
            self.assertEqual(result["enabled_residual"], case != "disabled")
            self.assertEqual(len(result["repeats"]), 2)
            self.assertEqual(len({row["checksum"] for row in result["repeats"]}), 1)
            for row in result["repeats"]:
                self.assertTrue(row["all_four_stages_exact"])
                self.assertEqual(row["processed_samples"], 66)
                self.assertGreater(row["cpu_seconds"], 0)
                self.assertGreater(row["wall_seconds"], 0)

    def test_one_ffi_call_per_case_repeat(self):
        library, function, record, record_hash = bench.load(self.library)
        with patch.object(bench, "load", return_value=(library, function, record, record_hash)):
            with patch.object(bench, "load") as load:
                from unittest.mock import Mock
                call = Mock(wraps=function)
                load.return_value = library, call, record, record_hash
                bench.run(self.library, count=5, iterations=3, repeats=2)
        self.assertEqual(call.call_count, 10)

    def test_work_budget_types_and_required_cap(self):
        for arguments in ({"count": True}, {"iterations": 0}, {"repeats": 21},
                          {"count": 65536, "iterations": 4096, "repeats": 1},
                          {"require_memory_cap": 1}):
            with self.assertRaises(ValueError): bench.run(self.library, **arguments)
        with patch.object(bench, "limits", return_value=None):
            with self.assertRaisesRegex(ValueError, "cgroup required"):
                bench.run(self.library, require_memory_cap=True)

    def test_native_iteration_reject_preserves_measurement(self):
        library, function, _, _ = bench.load(self.library)
        config, correction, planes, _ = bench.fixture("polynomial", 1)
        _, cfg = adapter._mapping(config)
        _, nlq = adapter._nlq(correction)
        inputs = [(C.c_uint16*1)(*plane) for plane in planes]
        outputs = [(kind*1)() for kind in (C.c_uint16,C.c_int32,C.c_int32,C.c_uint16)]
        for iterations in (0, 4097):
            result = bench.Measurement(12, 34, 56, 78)
            status = function(C.byref(cfg), C.byref(nlq), 1, *inputs, 1, 1, 12,
                              *outputs, iterations, C.byref(result))
            self.assertNotEqual(status, 0)
            self.assertEqual(tuple(getattr(result,name) for name,_ in bench.Measurement._fields_), (12,34,56,78))

    def test_explicit_fixtures_and_no_lto(self):
        for order in (1,2,3):
            mapping, _, planes, enabled = bench.fixture(f"mmr{order}", 17)
            self.assertEqual(len(mapping.mappings[1].segments[0].coefficients), order)
            self.assertTrue(enabled)
            self.assertEqual([len(plane) for plane in planes], [17]*4)
        with self.assertRaises(ValueError): bench.fixture("automatic", 1)
        _, _, record, _ = bench.load(self.library)
        self.assertIn("-fno-lto", record["command"])
        self.assertIn("native_kernel_bench.c", record["source_sha256"])

    def test_build_reuse_and_tampered_record_rejected(self):
        with self.assertRaises(FileExistsError): bench.build(self.library.parent)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            record = json.loads((self.library.parent/"build.json").read_text())
            record["source_sha256"] = {}
            (destination/"build.json").write_text(json.dumps(record))
            with patch.object(bench.C, "CDLL") as load:
                with self.assertRaises(ValueError): bench.load(destination/self.library.name)
                load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
