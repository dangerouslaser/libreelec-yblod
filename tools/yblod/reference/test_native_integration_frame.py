"""Synthetic host checks only; no films, devices or GPU dispatches."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import native_integration_frame as probe
import reference
import native_stage
import base_mapping_stage
import composition_stage
import nlq_stage
import streaming_composer
import test_colour_metadata


def bundle(test, *, mmr=False, disabled=False, native_library=None):
    fixture = test_colour_metadata.ColourMetadataTests(); fixture.setUp()
    test.addCleanup(fixture.doCleanups)
    if mmr:
        fixture.rpu["rpu_data_mapping"]["curves"][1] = {
            "num_pivots_minus2": 0, "pivots": [0, 1023], "mapping_idc": "MMR",
            "mmr_order_minus1": [0], "mmr_constant_int": [0], "mmr_constant": [0],
            "mmr_coef_int": [[[0, 1, 0, 0, 0, 0, 0]]], "mmr_coef": [[[0, 0, 0, 0, 0, 0, 0]]]}
        fixture.manifest["mmr_luma"] = "guide.u16le"
        (fixture.root/"prepared"/"guide.u16le").write_bytes(struct.pack("<2H", 123, 789))
    if disabled:
        fixture.rpu["rpu_data_mapping"]["nlq_method_idc"] = "NLQ_NONE"
        # normalize() uses the header disable-residual flag independently.
        fixture.rpu["header"]["disable_residual_flag"] = True
    fixture.manifest["metadata"] = test_colour_metadata.normalize(fixture.rpu, fixture.identity)
    if disabled: fixture.manifest["el"] = None
    fixture.refresh()
    path = fixture.root/"prepared"/"frame.json"
    path.write_text(json.dumps(fixture.manifest))
    baseline = fixture.root/"baseline"
    if native_library:
        streaming_composer.run(path, baseline, backend="native", native_library=native_library)
    else:
        reference.run(path, baseline)
    return fixture, path, baseline


class IntegrationFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"): raise unittest.SkipTest("C compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.library = probe.build(root/"adapter")
        cls.core = native_stage.build(root/"core")

    def execute(self, *, mmr=False, disabled=False, native=False, chunk=3):
        fixture, path, baseline = bundle(self, mmr=mmr, disabled=disabled, native_library=self.core if native else None)
        output = fixture.root/"private"
        with mock.patch.object(reference, "map_sample", side_effect=AssertionError("Python arithmetic called")), \
             mock.patch.object(reference, "inverse_el", side_effect=AssertionError("Python NLQ called")), \
             mock.patch.object(reference, "reconstruct", side_effect=AssertionError("Python composition called")), \
             mock.patch.object(base_mapping_stage, "map_sample", side_effect=AssertionError("Python mapping called")), \
             mock.patch.object(nlq_stage, "correction", side_effect=AssertionError("Python correction called")), \
             mock.patch.object(composition_stage, "compose", side_effect=AssertionError("Python compose called")):
            result = probe.run(self.library, path, baseline, fixture.extraction, output,
                               chunk_samples=chunk, require_memory_cap=False, allow_reference_baseline=not native)
        self.assertEqual(result["status"], "complete", (output/"private-report.json").read_text())
        self.assertEqual(result["completion"], dict(kind="arithmetic-frame-complete", counts=[8, 2, 2], diagnostic_queries=0))
        self.assertEqual(len(result["stages"]), 12)
        self.assertTrue(all(item["byte_exact"] for item in result["stages"].values()))
        return fixture, path, baseline, output, result

    def test_all_bytes_polynomial_mmr_disabled_and_chunk_sizes(self):
        for mmr, disabled, chunk in ((False, False, 1), (True, False, 3), (True, True, 65536)):
            with self.subTest(mmr=mmr, disabled=disabled, chunk=chunk):
                _, _, _, _, result = self.execute(mmr=mmr, disabled=disabled, chunk=chunk)
                self.assertEqual(result["enhancement_enabled"], not disabled)
                self.assertEqual(result["guide_consumed"], mmr)
                self.assertEqual(len([r for r in result["input_sha256"] if r.startswith("el_")]), 0 if disabled else 3)

    def test_native_baseline_default_and_reference_opt_in(self):
        self.execute(mmr=True, native=True)
        fixture, path, baseline = bundle(self)
        with self.assertRaisesRegex(ValueError, "native baseline"):
            probe.prepare(path, baseline, fixture.extraction)

    def test_build_pin_and_no_overwrite(self):
        with self.assertRaises(FileExistsError): probe.build(self.library.parent)
        fixture, path, baseline, output, _ = self.execute()
        before = (output/"public-summary.json").read_bytes()
        with self.assertRaises(FileExistsError):
            probe.run(self.library, path, baseline, fixture.extraction, output, require_memory_cap=False, allow_reference_baseline=True)
        self.assertEqual(before, (output/"public-summary.json").read_bytes())
        with mock.patch.object(probe, "source_hashes", return_value={"bad": "0"*64}):
            with self.assertRaisesRegex(ValueError, "provenance"):
                probe.Adapter(self.library, fixture.manifest, fixture.identity, {})

    def test_full_input_and_baseline_hashes_truncation_and_mutation(self):
        for role in ("input", "stage"):
            fixture, path, baseline = bundle(self, mmr=True)
            prepared = probe.prepare(path, baseline, fixture.extraction, allow_reference_baseline=True)
            specs, unchanged = prepared[2], prepared[-1]
            target = specs["bl_Y" if role == "input" else "sum_Cr"]
            file = target[0]/target[1]
            raw = file.read_bytes(); file.write_bytes(raw[:-1])
            with self.assertRaises(ValueError): unchanged()
            file.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            with self.assertRaises(ValueError): unchanged()

    def test_late_output_mismatch_never_complete(self):
        fixture, path, baseline = bundle(self)
        original = probe.Adapter.process
        def corrupt(adapter, component, start, planes, count):
            result = original(adapter, component, start, planes, count)
            if component == 2: return (b"\xff"*len(result[0]), *result[1:])
            return result
        output = fixture.root/"failed"
        with mock.patch.object(probe.Adapter, "process", corrupt):
            result = probe.run(self.library, path, baseline, fixture.extraction, output,
                               require_memory_cap=False, allow_reference_baseline=True)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["completion"])
        self.assertNotIn("error", result)

    def test_final_source_mutation_blocks_success(self):
        fixture, path, baseline = bundle(self)
        target = path.parent/fixture.manifest["bl"]["planes"]["Y"]
        original = probe.Adapter.finish
        def mutate(adapter, counts):
            answer = original(adapter, counts)
            target.write_bytes(target.read_bytes()+b"x")
            return answer
        with mock.patch.object(probe.Adapter, "finish", mutate):
            result = probe.run(self.library, path, baseline, fixture.extraction, fixture.root/"failed",
                               require_memory_cap=False, allow_reference_baseline=True)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["all_data_rechecked"])

    def test_reader_bounded_requests_and_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = b"\x00\x02"*23; (root/"plane").write_bytes(data)
            reader = probe.Reader(root, "plane", 23, 2, hashlib.sha256(data).hexdigest())
            try:
                with mock.patch.object(reader.stream, "read", wraps=reader.stream.read) as reads:
                    for n in (7, 7, 7, 2): reader.read(n)
                    reader.finish()
                    self.assertLessEqual(max(call.args[0] for call in reads.call_args_list), 14)
                with self.assertRaises(ValueError): reader.read(65537)
            finally: reader.close()
            with self.assertRaises(ValueError): probe.Reader(root, "../outside", 1, 2, "0"*64)

    def test_public_allowlist_and_success_guards(self):
        _, _, _, output, _ = self.execute(mmr=True)
        private = json.loads((output/"private-report.json").read_text())
        private.update(secret="/private/movie-title.mkv", pixels=[123, 456], coefficients=[999], error={"message": "secret-title"})
        rendered = json.dumps(probe.public_summary(private))
        for forbidden in ("movie-title", "coefficients", "pixels", "secret-title", "frame_id", "pts"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(probe.public_summary(private)["memory_guard_state"], "bypassed-host-test")
        for field in ("association_verified", "all_data_rechecked"):
            bad = copy.deepcopy(private); bad[field] = False
            with self.assertRaises(ValueError): probe.public_summary(bad)
        bad = copy.deepcopy(private); bad["memory_cap_required"] = True
        with self.assertRaises(ValueError): probe.public_summary(bad)
        for mutation in ("stage", "input", "source", "completion"):
            bad = copy.deepcopy(private)
            if mutation == "stage": bad["stages"].pop("sum_Y")
            elif mutation == "input": bad["input_sha256"]["private-title"] = "a"*64
            elif mutation == "source": bad["source_sha256"].pop("extract_frame.py")
            else: bad["completion"]["diagnostic_queries"] = False
            with self.assertRaises(ValueError): probe.public_summary(bad)

    def test_cgroup_cap_and_pressure_fail_closed(self):
        before = {"memory.max": str(512*1024**2), "memory.swap.max": "0", "memory.swap.current": "0",
                  "memory.events": "max 0\noom 0\noom_kill 0"}
        self.assertTrue(probe.memory_valid(before, before))
        for key, value in (("memory.max", "max"), ("memory.swap.current", "1"), ("memory.events", "max 1\noom 0\noom_kill 0")):
            after = dict(before); after[key] = value
            self.assertFalse(probe.memory_valid(before, after))

    def test_late_memory_event_prevents_complete_report(self):
        fixture, path, baseline = bundle(self)
        before = {"memory.max": str(512*1024**2), "memory.swap.max": "0", "memory.swap.current": "0",
                  "memory.events": "max 0\noom 0\noom_kill 0", "memory.peak": "1000000"}
        after = dict(before, **{"memory.events": "max 1\noom 0\noom_kill 0"})
        with mock.patch.object(probe, "memory_snapshot", side_effect=(before, after)):
            result = probe.run(self.library, path, baseline, fixture.extraction, fixture.root/"pressure",
                               allow_reference_baseline=True)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["memory_guard_passed"])
        self.assertEqual(result["resources"]["limit_events"], 1)

    def test_source_inventory_imports_in_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in probe.SOURCES: shutil.copyfile(probe.ROOT/name, Path(directory)/name)
            result = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0,{directory!r}); import native_integration_frame"],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_abi_queries_are_rejected_before_initialization(self):
        fixture, _, _ = bundle(self)
        actual = probe.C.CDLL
        for query in ("yb_integration_abi_version", "yb_integration_sizeof_context"):
            class Proxy:
                def __init__(self, library): self.library = actual(library)
                def __getattr__(self, name):
                    if name == query: return mock.Mock(return_value=999)
                    return getattr(self.library, name)
            with mock.patch.object(probe.C, "CDLL", Proxy):
                with self.assertRaisesRegex(ValueError, "ABI"):
                    probe.Adapter(self.library, fixture.manifest, fixture.identity, {})

    def test_stale_association_trailing_data_and_symlink_rejected(self):
        fixture, path, baseline = bundle(self)
        fixture.extracted["source_packet_index_zero_based"] += 1
        fixture.refresh()
        with self.assertRaises(ValueError): probe.prepare(path, baseline, fixture.extraction, allow_reference_baseline=True)
        fixture, path, baseline = bundle(self)
        file = path.parent/fixture.manifest["bl"]["planes"]["Y"]
        original = file.read_bytes(); file.write_bytes(original+b"\x00\x00")
        with self.assertRaises(ValueError): probe.prepare(path, baseline, fixture.extraction, allow_reference_baseline=True)
        file.write_bytes(original)
        link = path.parent/"alias"; link.symlink_to(file.name)
        with self.assertRaisesRegex(ValueError, "symlink"):
            probe.Reader(path.parent, "alias", 8, 2, hashlib.sha256(original).hexdigest())

    def test_one_c_dispatch_per_component_chunk(self):
        fixture, path, baseline = bundle(self, mmr=True)
        actual_init = probe.Adapter.__init__
        observed = []
        def initialize(adapter, *args, **kwargs):
            actual_init(adapter, *args, **kwargs)
            function = adapter.lib.yb_integration_integer
            def counted(*call):
                observed.append((call[2], call[3], call[8]))
                return function(*call)
            adapter.lib.yb_integration_integer = counted
        with mock.patch.object(probe.Adapter, "__init__", initialize):
            result = probe.run(self.library, path, baseline, fixture.extraction, fixture.root/"calls",
                               chunk_samples=3, require_memory_cap=False, allow_reference_baseline=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(observed, [(0,0,3), (0,3,3), (0,6,2), (1,0,2), (2,0,2)])


if __name__ == "__main__": unittest.main()
