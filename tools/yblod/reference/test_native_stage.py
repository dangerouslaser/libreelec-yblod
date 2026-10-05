import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import native_stage as native
from base_mapping_stage import BaseMappingConfig, map_sample
from composition_stage import compose_residual
from nlq_stage import NLQConfig, correction


def configs(depth=10, denominator=23, mmr=False):
    mappings = [{"pivots": [0, (1 << depth)-1],
                 "segments": [{"method": "polynomial", "coefficients": [0, 1 << denominator]}]}
                for _ in range(3)]
    if mmr:
        for component in (1, 2):
            mappings[component]["segments"] = [{"method": "mmr", "constant": 173,
                "coefficients": [[12345, -23456, 34567, -45678, 56789, -67890, 78901],
                                  [-123, 234, -345, 456, -567, 678, -789]]}]
    mapping = BaseMappingConfig.from_mappings(mappings, bit_depth=depth, denominator=denominator)
    nlqs = [NLQConfig(depth, denominator, 1 << (depth-1), 2048+i, i*3, 1025+i) for i in range(3)]
    return mapping, nlqs


class NativeStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.library = native.build(cls.root/"build")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def stage(self, *, disabled=False, mmr=False, depth=10, denominator=23, output=12):
        mapping, nlqs = configs(depth, denominator, mmr)
        return native.NativeStage(self.library, mapping, None if disabled else nlqs,
                                  output, disabled=disabled), mapping, nlqs

    def test_differential_all_channels_and_depths(self):
        for depth, denominator in ((8, 13), (10, 15), (10, 23), (8, 32)):
            for output in (10, 12):
                for mmr in (False, True):
                    stage, mapping, nlqs = self.stage(depth=depth, denominator=denominator,
                                                       output=output, mmr=mmr)
                    top = (1 << depth)-1
                    triples = [(0, 1, top), (top, top//2, 0), (top//2, top//3, top//4)]
                    samples = [0, top//2, top]
                    for component in range(3):
                        result = stage.process(component, triples, samples)
                        mapped = [map_sample(component, row, mapping) for row in triples]
                        residual = [correction(s, nlqs[component]) for s in samples]
                        self.assertEqual(result, dict(mapped=mapped, residual=residual,
                            sum=[a+b for a,b in zip(mapped,residual)],
                            reconstructed=[compose_residual(a,b,output) for a,b in zip(mapped,residual)]))

    def test_disabled_and_explicit_zero_planes(self):
        stage, mapping, _ = self.stage(disabled=True)
        result = stage.process_planes(0, [0, 512, 1023], None, None)
        self.assertEqual(result["residual"], [0]*3)
        self.assertEqual(result["mapped"], [map_sample(0, (s,0,0), mapping) for s in (0,512,1023)])
        with self.assertRaises(ValueError):
            stage.process_planes(0, [1], None, None, [512])

    def test_single_native_call_per_chunk(self):
        stage, _, _ = self.stage()
        with patch.object(stage, "_process", wraps=stage._process) as call:
            result = stage.process_planes(0, range(1024), None, None, [512]*1024)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(len(result["mapped"]), 1024)

    def test_strict_values_lengths_and_bounded_iterators(self):
        stage, _, _ = self.stage()
        for bad in (True, 1.5, -1, 1024, 65536):
            with self.assertRaises(ValueError):
                stage.process_planes(0, [bad], None, None, [512])
            with self.assertRaises(ValueError):
                stage.process_planes(0, [1], None, None, [bad])
        for args in ((0, [], None, None, []), (True, [1], None, None, [1]),
                     (0, [1], [1,2], None, [1]), (0, [1], None, None, []),
                     (0, None, [1], [2], [1])):
            with self.assertRaises(ValueError): stage.process_planes(*args)
        with self.assertRaises(ValueError):
            stage.process_planes(0, itertools.repeat(1), None, None, [512])
        with self.assertRaises(ValueError): stage.process(0, [(1,2)], [512])

    def test_mmr_requires_all_explicit_inputs(self):
        stage, _, _ = self.stage(mmr=True)
        for planes in ((None,[1],[2]), ([1],[2],None), ([1],None,[2])):
            with self.assertRaisesRegex(ValueError, "MMR requires"):
                stage.process_planes(1, *planes, [512])

    def test_configuration_revalidated_and_copied(self):
        mapping, nlqs = configs()
        stage = native.NativeStage(self.library, mapping, nlqs, 12)
        before = stage.process_planes(0, [512], None, None, [513])
        object.__setattr__(nlqs[0], "slope", True)
        object.__setattr__(mapping, "bit_depth", True)
        self.assertEqual(stage.process_planes(0, [512], None, None, [513]), before)
        with self.assertRaises(ValueError): native.NativeStage(self.library, mapping, nlqs, 12)
        mapping, nlqs = configs()
        for kwargs in ({"disabled": 1}, {"output_depth": True}):
            options = dict(output_depth=12)
            options.update(kwargs)
            with self.assertRaises(ValueError): native.NativeStage(self.library, mapping, nlqs, **options)
        with self.assertRaises(ValueError): native.NativeStage(self.library, mapping, nlqs, 12, disabled=True)

    def test_build_record_and_binary_mismatch_rejected_before_load(self):
        for field, value in (("abi_version", True), ("status", "failed"),
                             ("library_sha256", "0"*64), ("source_sha256", {})):
            with tempfile.TemporaryDirectory() as temporary:
                copied = Path(temporary)/self.library.name
                shutil.copyfile(self.library, copied)
                record = json.loads((self.library.parent/"build.json").read_text())
                record[field] = value
                (copied.parent/"build.json").write_text(json.dumps(record))
                with patch.object(native.C, "CDLL") as load:
                    with self.assertRaises(ValueError): native.NativeStage(copied, *configs(), 12)
                    load.assert_not_called()

    def test_source_change_and_no_overwrite(self):
        with patch.object(native, "source_hashes", return_value={}):
            with self.assertRaises(ValueError): native.NativeStage(self.library, *configs(), 12)
        with self.assertRaises(FileExistsError): native.build(self.library.parent)
        stage, _, _ = self.stage()
        self.assertEqual(stage.provenance["library_sha256"], native.digest(self.library))
        self.assertIn("native_composer.h", stage.provenance["source_sha256"])

    def test_record_fail_closed_before_library_load(self):
        for raw in (b'[]', b'{"schema":1,"schema":2}', b'{"x":NaN}',
                    b'{"x":1e999}', b' '*(1024*1024+1)):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)
                (path/"build.json").write_bytes(raw)
                with patch.object(native.C, "CDLL") as load:
                    with self.assertRaises(ValueError):
                        native.NativeStage(path/"libnative_composer.so", *configs(), 12)
                    load.assert_not_called()

    def test_fifo_record_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            os.mkfifo(path/"build.json")
            with self.assertRaisesRegex(ValueError, "regular file"):
                native.NativeStage(path/"libnative_composer.so", *configs(), 12)

    def test_library_change_during_load_rejected(self):
        real_digest = native.digest
        calls = 0
        def changed(path):
            nonlocal calls
            if Path(path) == self.library:
                calls += 1
                if calls == 2: return "0"*64
            return real_digest(path)
        with patch.object(native, "digest", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during load"):
                native.NativeStage(self.library, *configs(), 12)


if __name__ == "__main__":
    unittest.main()
