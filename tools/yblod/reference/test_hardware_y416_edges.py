"""Synthetic step/stripe fixtures and fake hardware only."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_y416_edges as edges


class EdgeFixtureTests(unittest.TestCase):
    def test13cases_component_isolation_step_impulse_and_tags(self):
        self.assertEqual(len(edges.CASES),13)
        for case in edges.CASES:
            spec=edges.case_spec(case);planes=edges.input_planes(case)
            for c,rows in planes.items():
                extent=64 if c=="Y" else 32
                count=sum(v==576 for row in rows for v in row)
                expected=0 if c!=spec["component"] else (extent*extent//2 if spec["kind"]=="step" else extent)
                self.assertEqual(count,expected)
                self.assertTrue(all(v in (512,576) for row in rows for v in row))
                for y,row in enumerate(rows):
                    for x,v in enumerate(row):
                        coordinate=x if spec["axis"]=="x" else y
                        driven=c==spec["component"] and (coordinate>=spec["change_native_index"] if spec["kind"]=="step" else coordinate==spec["change_native_index"])
                        self.assertEqual(v,512+64*int(driven))

    def test_baseline_comparison_preserves_alpha_and_rawlowbits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,b=root/"a.y416",root/"b.y416"
            a.write_bytes(struct.pack("<4H",32752,32752,32752,65280)*4096)
            data=bytearray(a.read_bytes());data[8*100:8*100+2]=(32751).to_bytes(2,"little")
            data[8*200+6:8*200+8]=(65281).to_bytes(2,"little");b.write_bytes(data)
            result=edges.compare_baseline(b,a,64)
            self.assertEqual(result["raw_word_positions"]["0"]["different"],1)
            self.assertEqual(result["raw_word_positions"]["0"]["sum_signed_raw_delta"],-1)
            self.assertEqual(result["raw_word_positions"]["3"]["different"],1)
            self.assertEqual(result["raw_word_positions"]["3"]["sum_signed_raw_delta"],1)


class EdgeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.binary=self.root/"fake";self.binary.write_bytes(b"synthetic fakehardware")
        self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":30,"check":False});self.calls.append(argv)
        size=int(argv[6]);copy=argv[8]=="copy";fmt="p010" if copy else argv[14]
        checker=edges.spatial.checker
        if fmt=="p010":shutil.copyfile(argv[2],argv[3])
        else:
            source=checker.transport.unpack_p010(Path(argv[2]).read_bytes(),64,64);scale=size//64
            data=b"".join(struct.pack("<4H",source["Cb"][y//(2*scale)][x//(2*scale)]*64,
                                       source["Y"][y//scale][x//scale]*64,
                                       source["Cr"][y//(2*scale)][x//(2*scale)]*64,65535 if size==64 else 65280)
                          for y in range(size) for x in range(size))
            if self.fault=="unstable" and argv[3].endswith("-1.y416"):data=bytes([data[0]^1])+data[1:]
            if self.fault=="size":data=data[:-1]
            Path(argv[3]).write_bytes(data)
        if self.fault=="identity" and fmt=="p010":
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        value={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete","vendor":"synthetic fake","va_version":[1,24],
               "input_size":[64,64],"output_size":[size,size],"filter_flags":0,
               "input_fourcc":checker.FOURCC["p010"],"output_fourcc":checker.FOURCC[fmt],
               "input_rt_format":checker.RT_FORMAT["p010"],"output_rt_format":checker.RT_FORMAT[fmt],
               "output_packed_bytes":size*size*(3 if fmt=="p010" else 8),"input_chroma_siting":None if copy else 6,
               "output_chroma_siting":None if copy else (6 if fmt=="p010" else 0),"colour_standard":None if copy else 12,
               "colour_range":None if copy else (2 if fmt=="p010" else 1),"pipeline_flags":None if copy else 0,
               "pipeline_caps_flags":None if copy else 2,"vpp_submitted":not copy,"hardware_engine_verified":False,
               "surface_contract":"allocation-diagnostic" if fmt=="y416" else "advertised",
               "output_surface_advertised":None if copy else fmt=="p010","drm_client_engine_accounting":{"synthetic":True}}
        if self.fault=="metadata" and fmt=="y416":value["colour_range"]=2
        if self.fault=="timeout":raise subprocess.TimeoutExpired(argv,30,output=b"partial")
        if self.fault=="nonzero":return subprocess.CompletedProcess(argv,1,b"",b"syntheticfailure")
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name):
        with patch.object(edges.subprocess,"run",side_effect=self.fake),patch.object(edges.sys,"stderr",io.StringIO()):
            result=edges.run(self.binary,self.root/name)
        self.assertEqual(result,json.loads((self.root/name/"y416-edges-report.json").read_text()));return result

    def test78jobs_native_gates_before_all_conversions_alpha_notforcedopaque(self):
        result=self.execute("complete");self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),78)
        self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:26]));self.assertTrue(all(c[6]=="64" for c in self.calls[:52]))
        self.assertTrue(all(c[6]=="128" for c in self.calls[52:]))
        for size,cases in result["results"].items():
            self.assertEqual(set(cases),set(edges.CASES))
            for case,result in cases.items():
                self.assertTrue(result["repeat_stable"])
                driven=edges.spatial.UYVA[edges.case_spec(case)["component"]] if case!="neutral" else None
                for index,value in result["differences_from_neutral"]["raw_word_positions"].items():
                    self.assertEqual(value["samples"],int(size)**2)
                    if int(index)!=driven:self.assertEqual(value["different"],0)
                self.assertEqual(result["alpha_raw_word_values_under_UYVA"],[65535 if size=="64" else 65280])

    def check_failure(self,fault):
        self.fault=fault;result=self.execute(fault);self.assertEqual(result["status"],"failed")
        self.assertIn("stdout",result["invocations"][-1]);self.assertIn("stderr",result["invocations"][-1])
        return result

    def test_identity_failure(self):
        self.check_failure("identity");self.assertEqual(len(self.calls),1)

    def test_metadata_failure(self):self.check_failure("metadata")
    def test_rawsize_failure(self):self.check_failure("size")
    def test_repeat_failure(self):self.check_failure("unstable")
    def test_nonzero_failure(self):self.check_failure("nonzero")
    def test_timeout_failure(self):self.check_failure("timeout")


if __name__=="__main__":unittest.main()
