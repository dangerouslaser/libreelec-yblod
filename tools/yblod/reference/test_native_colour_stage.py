import itertools
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import colour_stage
import native_colour_stage as native
from test_colour_stage import config, IDENTITY, UNIT, EXTEND


class NativeColourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.library = native.build(Path(cls.temporary.name)/"build")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def assert_results(self, actual, expected):
        self.assertEqual(actual.codes, expected.codes)
        for name in ("source_nonlinear", "common_linear_lms", "target_linear", "transport_before_quantization"):
            for a, b in zip(getattr(actual, name), getattr(expected, name)):
                self.assertTrue(math.isclose(a, b, rel_tol=2e-11, abs_tol=2e-12), (name, a, b))

    def test_differential_fractional_inputs_and_one_chunk_call(self):
        samples = [(float(y), cb+.25, cr+.5) for y, cb, cr in
                   itertools.product((0, 128, 2048, 4095), (0, 777, 4094), (0, 333, 4094))]
        for policy in (UNIT, EXTEND):
            cfg = config(policy=policy)
            stage = native.NativeColourStage(self.library, cfg)
            expected = [colour_stage.convert_sample(row, cfg) for row in samples]
            with patch.object(stage, "_process", wraps=stage._process) as process:
                with patch.object(colour_stage, "convert_sample", side_effect=AssertionError("Python arithmetic reached")):
                    actual = stage.convert_chunk(iter(samples))
            self.assertEqual(process.call_count, 1)
            for a, b in zip(actual, expected): self.assert_results(a, b)

    def test_configuration_copy_and_revalidation(self):
        cfg = config()
        stage = native.NativeColourStage(self.library, cfg)
        expected = stage.convert_chunk([(512, 512, 512)])
        object.__setattr__(cfg, "code_scale", True)
        self.assertEqual(stage.convert_chunk([(512, 512, 512)]), expected)
        with self.assertRaises(ValueError): native.NativeColourStage(self.library, cfg)
        with self.assertRaises(ValueError): native.NativeColourStage(self.library, {})

    def test_bad_samples_empty_and_bounded_iterator(self):
        stage = native.NativeColourStage(self.library, config())
        for rows in ([], [(1,2)], [(True,1,2)], [(math.nan,1,2)], [(math.inf,1,2)],
                     [(-1,1,2)], [(4096,1,2)], [("1",1,2)]):
            with self.assertRaises(ValueError): stage.convert_chunk(rows)
        with self.assertRaises(ValueError): stage.convert_chunk(itertools.repeat((1,2,3)))

    def test_domain_failure_and_explicit_extended_policy(self):
        source = tuple(tuple(value*2 for value in row) for row in IDENTITY)
        cfg = colour_stage.ColourConfig(source, (0,0,0), IDENTITY, IDENTITY,
                                       (0,0,0), IDENTITY, UNIT, 4096)
        strict = native.NativeColourStage(self.library, cfg)
        with self.assertRaisesRegex(ValueError, "chunk rejected"):
            strict.convert_chunk([(512,512,512), (3000,3000,3000)])
        extended = colour_stage.ColourConfig(source, (0,0,0), IDENTITY, IDENTITY,
                                            (0,0,0), IDENTITY, EXTEND, 4096)
        result = native.NativeColourStage(self.library, extended).convert_chunk([(3000,3000,3000)])[0]
        self.assertGreater(max(result.common_linear_lms), 1)
        self.assert_results(result, colour_stage.convert_sample((3000,3000,3000), extended))

    def test_pins_flags_and_no_overwrite(self):
        stage = native.NativeColourStage(self.library, config())
        self.assertEqual(stage.provenance["library_sha256"], native.digest(self.library))
        command = stage.provenance["build_record"]["command"]
        for flag in ("-lm", "-fno-fast-math", "-ffp-contract=off"):
            self.assertIn(flag, command)
        with self.assertRaises(FileExistsError): native.build(self.library.parent)
        with patch.object(native, "source_hashes", return_value={}):
            with self.assertRaises(ValueError): native.NativeColourStage(self.library, config())

    def test_invalid_record_rejected_before_load(self):
        for raw in (b'[]', b'{"x":1,"x":2}', b'{"x":1e999}'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)
                (path/"build.json").write_bytes(raw)
                with patch.object(native.C, "CDLL") as load:
                    with self.assertRaises(ValueError): native.NativeColourStage(path/"libnative_colour.so", config())
                    load.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            record = json.loads((self.library.parent/"build.json").read_text())
            record["abi_version"] = True
            (path/"build.json").write_text(json.dumps(record))
            with patch.object(native.C, "CDLL") as load:
                with self.assertRaises(ValueError): native.NativeColourStage(path/self.library.name, config())
                load.assert_not_called()

    def test_actual_native_frame_bytes_and_statistics(self):
        import colour_frame
        from test_colour_frame import ColourFrameTests
        fixture = ColourFrameTests(methodName="test_output_sizes_hashes_and_bounded_cache")
        fixture.setUp()
        try:
            fixture.config["active_rectangle"] = [2,1,30,17]
            fixture.save()
            expected = colour_frame.run(fixture.result, fixture.config_path, fixture.root/"python")
            with patch.object(colour_stage, "convert_sample", side_effect=AssertionError("Python colour arithmetic reached")):
                actual = colour_frame.run(fixture.result, fixture.config_path, fixture.output,
                                          backend="native", native_library=self.library)
            self.assertEqual(actual["backend"], "native")
            self.assertEqual(actual["stages"], expected["stages"])
            for stage in actual["stages"].values():
                self.assertEqual((fixture.output/stage["file"]).read_bytes(),
                                 (fixture.root/"python"/stage["file"]).read_bytes())
            for group, values in actual["statistics"].items():
                for key, value in values.items():
                    target = expected["statistics"][group][key]
                    if type(value) is int: self.assertEqual(value, target)
                    else: self.assertTrue(math.isclose(value, target, rel_tol=2e-11, abs_tol=2e-12))
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
