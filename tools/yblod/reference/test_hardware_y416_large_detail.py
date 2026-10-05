"""Small deterministic fixtures and fake subprocesses, never GPU."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_y416_large_detail as detail


class LargeDetailFixtureTests(unittest.TestCase):
    def test_descending_mirrors_ascending_to1016_with_center504(self):
        for case in detail.CORPORA["descending"][1:]:
            spec=detail.case_spec(case);ascending=detail.large.case_spec(case.replace("descending","ascending"))
            self.assertEqual(spec["band_first_code"],888);self.assertEqual(spec["band_last_code"],128)
            for m in (0,spec["band_start_native"],spec["source_center_native_index"],spec["band_stop_native_exclusive"]-1,10000):
                x,y=(m,0) if spec["axis"]=="x" else (0,m)
                self.assertEqual(detail.source_code(spec,spec["component"],x,y)+detail.large.source_code(ascending,spec["component"],x,y),1016)
            m=spec["source_center_native_index"];self.assertEqual(detail.source_code(spec,spec["component"],m if spec["axis"]=="x" else 0,m if spec["axis"]=="y" else 0),504)

    def test_steps_and_source_integer_stripe_placements(self):
        self.assertEqual([len(c) for c in detail.CORPORA.values()],[7,7,13])
        for corpus in ("edges","stripes"):
            for case in detail.CORPORA[corpus][1:]:
                spec=detail.case_spec(case);center=spec["change_native_index"]
                for m in (center-1,center,center+1):
                    value=detail.source_code(spec,spec["component"],m if spec["axis"]=="x" else 0,m if spec["axis"]=="y" else 0)
                    self.assertEqual(value,576 if (m>=center if corpus=="edges" else m==center) else 512)
                if corpus=="stripes":
                    self.assertEqual(spec["source_index_offset"],spec["phase"])
                    self.assertIn("not a fractional",spec["placement_interpretation"])
                    self.assertEqual(spec["integer_output_translation_hypothesis"]["scaled"],spec["phase"]*(2 if spec["component"]=="Y" else 4))

    def test_stream_generation_small_corpus_exact_and_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for corpus,cases in detail.CORPORA.items():
                for case in cases:
                    path=root/f"{corpus}-{case}.p010";record=detail.generate(path,case,128,128);spec=record["case_spec"]
                    planes={c:[[detail.source_code(spec,c,x,y) for x in range(128 if c=="Y" else 64)]
                               for y in range(128 if c=="Y" else 64)] for c in detail.large.checker.transport.CHANNELS}
                    self.assertEqual(path.read_bytes(),detail.large.checker.transport.pack_p010(planes))
                    self.assertTrue(detail.large.p010_identity(path,record,128,128)["exact"])


class LargeDetailRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.binary=self.root/"fake";self.binary.write_bytes(b"synthetic fakehardware");self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":60,"check":False});self.calls.append(argv)
        iw,ih,ow,oh=map(int,argv[4:8]);copy=argv[8]=="copy";fmt="p010" if copy else argv[14];checker=detail.large.checker
        if fmt=="p010":shutil.copyfile(argv[2],argv[3])
        else:
            planes=checker.transport.unpack_p010(Path(argv[2]).read_bytes(),iw,ih);scale=ow//iw
            data=b"".join(struct.pack("<4H",planes["Cb"][y//(2*scale)][x//(2*scale)]*64,
                                       planes["Y"][y//scale][x//scale]*64,planes["Cr"][y//(2*scale)][x//(2*scale)]*64,
                                       65535 if scale==1 else 65280) for y in range(oh) for x in range(ow))
            if self.fault=="unstable" and argv[3].endswith("-1.y416"):data=bytes([data[0]^1])+data[1:]
            if self.fault=="size":data=data[:-1]
            Path(argv[3]).write_bytes(data)
        if self.fault=="identity" and fmt=="p010":
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        value={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete","vendor":"synthetic fake","va_version":[1,24],
               "input_size":[iw,ih],"output_size":[ow,oh],"filter_flags":0,"input_fourcc":checker.FOURCC["p010"],"output_fourcc":checker.FOURCC[fmt],
               "input_rt_format":checker.RT_FORMAT["p010"],"output_rt_format":checker.RT_FORMAT[fmt],"output_packed_bytes":ow*oh*(3 if fmt=="p010" else 8),
               "input_chroma_siting":None if copy else 6,"output_chroma_siting":None if copy else (6 if fmt=="p010" else 0),
               "colour_standard":None if copy else 12,"colour_range":None if copy else (2 if fmt=="p010" else 1),"pipeline_flags":None if copy else 0,
               "pipeline_caps_flags":None if copy else 2,"vpp_submitted":not copy,"hardware_engine_verified":False,
               "surface_contract":"allocation-diagnostic" if fmt=="y416" else "advertised","output_surface_advertised":None if copy else fmt=="p010"}
        if self.fault=="metadata" and fmt=="y416":value["colour_range"]=2
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name,corpus):
        with patch.object(detail.subprocess,"run",side_effect=self.fake),patch.object(detail.sys,"stderr",io.StringIO()):
            result=detail.run(self.binary,self.root/name,corpus,128,128)
        self.assertEqual(result,json.loads((self.root/name/"y416-large-detail-report.json").read_text()));return result

    def test_each_corpus_checkpoint_retains_every_raw_and_native_gates_first(self):
        for corpus in detail.CORPORA:
            self.calls=[];result=self.execute(corpus,corpus);count=len(detail.CORPORA[corpus])
            self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),6*count)
            self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:2*count]))
            self.assertTrue(all(c[6]=="128" for c in self.calls[:4*count]));self.assertTrue(all(c[6]=="256" for c in self.calls[4*count:]))
            self.assertTrue(all(Path(call[3]).exists() for call in self.calls))
            self.assertEqual(result["case_count"],count);self.assertIn("own_cgroup_memory",result["resources"])

    def test_failures_retain_evidence(self):
        for fault in ("identity","metadata","size","unstable"):
            self.fault,self.calls=fault,[];result=self.execute(fault,"descending");self.assertEqual(result["status"],"failed")

    def test_disk_guard_blocks_before_any_gpu_job_without_deleting(self):
        with patch.object(detail.shutil,"disk_usage",return_value=shutil._ntuple_diskusage(100,99,1)),patch.object(detail.subprocess,"run",side_effect=self.fake):
            result=detail.run(self.binary,self.root/"disk","descending",128,128)
        self.assertEqual(result["status"],"failed");self.assertEqual(self.calls,[]);self.assertEqual(result["inputs"],{})


if __name__=="__main__":unittest.main()
