"""Synthetic native blobs only; Python fixture generation is not real ingestion."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import native_decoder_frame as bridge
import native_integration_frame as frame
import native_stage as native
from base_mapping_stage import BaseMappingConfig
from nlq_stage import NLQConfig
from test_native_decoder_frame_bridge import Instructions
from test_native_integration_frame import bundle

class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);cls.library=root/"bridge.so"
        subprocess.run(["cc","-std=c11","-O2","-shared","-fPIC","-Wall","-Wextra","-Werror",
                        "-Wconversion","-Wshadow",*(str(bridge.ROOT/p) for p in
                        ("native_decoder_frame_bridge.c","native_integration_probe.c",
                         "native_composer.c","native_sampling_probe.c")),"-o",str(cls.library)],check=True)
        cls.core=native.build(root/"core")
    def fixture(self,mmr=False,disabled=False):
        fixture,path,baseline=bundle(self,mmr=mmr,disabled=disabled,native_library=self.core)
        m=fixture.manifest["metadata"];obj=Instructions();obj.version=1
        obj.enabled=int(not m["disable_residual"]);obj.depth=m["output_bit_depth"]
        obj.mapping=native._mapping(BaseMappingConfig.from_mappings(m["mappings"],bit_depth=m["bl_bit_depth"],denominator=m["coefficient_log2_denom"]))[1]
        if obj.enabled:
            for i,values in enumerate(m["nlq"]):
                obj.nlq[i]=native._nlq(NLQConfig.from_mapping(values,bit_depth=m["el_bit_depth"],denominator=m["coefficient_log2_denom"]))[1]
        blob=fixture.root/"synthetic-instructions.bin";blob.write_bytes(bytes(obj))
        return fixture,path,baseline,blob
    def execute(self,values,chunk=3):
        fixture,path,baseline,blob=values
        return bridge.compare(self.library,blob,native.digest(blob),path,baseline,fixture.extraction,
                              library_sha256=native.digest(self.library),chunk_samples=chunk,require_memory_cap=False)
    def test_all_stages_and_no_json_instruction_constructor(self):
        for mmr,disabled,chunk in ((False,False,1),(True,False,3),(True,True,65536)):
            values=self.fixture(mmr,disabled)
            with mock.patch.object(frame.Adapter,"__init__",side_effect=AssertionError("JSON instructions used")):
                result=self.execute(values,chunk)
            self.assertEqual(result["status"],"complete");self.assertEqual(len(result["stages"]),12)
            self.assertEqual(result["completion"]["counts"],[8,2,2])
    def test_bad_blob_digest_and_truncation_rejected(self):
        values=self.fixture();blob=values[3]
        with self.assertRaises(ValueError):
            bridge.compare(self.library,blob,"0"*64,*values[1:3],values[0].extraction,
                           library_sha256=native.digest(self.library),require_memory_cap=False)
        blob.write_bytes(blob.read_bytes()[:-1])
        with self.assertRaises(ValueError):self.execute(values)

if __name__=="__main__": unittest.main()
