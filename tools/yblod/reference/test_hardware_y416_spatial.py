"""Synthetic profiles and fake VPP; no GPU or fitted expected geometry."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_y416_spatial as spatial


class SpatialProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test13_isolated_case_specs_match_every_source_sample(self):
        self.assertEqual(len(spatial.CASES),13)
        for case in spatial.CASES:
            spec=spatial.case_spec(case);planes=spatial.input_planes(case)
            for c,rows in planes.items():
                extent=64 if c=="Y" else 32
                self.assertEqual(spec["native_component_sizes"][c],[extent,extent])
                for y,row in enumerate(rows):
                    for x,v in enumerate(row):
                        expected=spec["base_codes_at_origin"][c]+(spec["signed_slope"]*(x if spec["axis"]=="x" else y) if c==spec["component"] else 0)
                        self.assertEqual(v,expected);self.assertTrue(64<=v<=940)
                if c!=spec["component"]:self.assertTrue(all(v==512 for row in rows for v in row))
        self.assertEqual(spatial.case_spec("Y-x-descending")["base_codes_at_origin"]["Y"],768)
        self.assertEqual(spatial.case_spec("Cb-y-descending")["base_codes_at_origin"]["Cb"],640)
        self.assertEqual(spatial.input_planes("Y-x-descending")["Y"][32][32],512)
        self.assertEqual(spatial.input_planes("Cr-y-descending")["Cr"][16][16],512)

    def test_raw_center_profiles_full_pixel_indices_and_lowbits_preserved(self):
        for size in (64,128):
            path=self.root/f"{size}.y416"
            path.write_bytes(b"".join(struct.pack("<4H",100+x,200+y,300+x+y,65535) for y in range(size) for x in range(size)))
            result=spatial.analyse(path,size);positions=result["raw_le16_word_positions"]
            self.assertEqual(positions["0"]["center_row_raw_words"],list(range(100,100+size)))
            self.assertEqual(positions["1"]["center_column_raw_words"],list(range(200,200+size)))
            self.assertEqual(positions["2"]["center_row_raw_words"],[300+size//2+x for x in range(size)])
            self.assertEqual(positions["3"]["raw_word_values"],[65535])
            for v in positions.values():
                self.assertEqual(sum(v["low4_histogram"]),size*size);self.assertEqual(sum(v["low6_histogram"]),size*size)
                self.assertEqual(len(v["center_row_raw_words"]),size);self.assertEqual(len(v["center_column_raw_words"]),size)
            self.assertGreater(positions["0"]["low4_histogram"][1],0)

    def test_strict_frame_sizes(self):
        path=self.root/"bad.y416";data=struct.pack("<4H",0,0,0,65535)*4096
        for bad in (data[:-1],data+b"\x00"):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):spatial.analyse(path,64)


class SpatialRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.binary=self.root/"fake";self.binary.write_bytes(b"synthetic fakehardware")
        self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":30,"check":False});self.calls.append(argv)
        size=int(argv[6]);copy=argv[8]=="copy";fmt="p010" if copy else argv[14]
        if fmt=="p010":shutil.copyfile(argv[2],argv[3])
        else:
            source=spatial.checker.transport.unpack_p010(Path(argv[2]).read_bytes(),64,64)
            scale=size//64
            data=b"".join(struct.pack("<4H",source["Cb"][y//(2*scale)][x//(2*scale)]*64,
                                       source["Y"][y//scale][x//scale]*64,
                                       source["Cr"][y//(2*scale)][x//(2*scale)]*64,65535)
                          for y in range(size) for x in range(size))
            if self.fault=="unstable" and argv[3].endswith("-1.y416"):data=bytes([data[0]^1])+data[1:]
            if self.fault=="size":data=data[:-1]
            Path(argv[3]).write_bytes(data)
        if self.fault=="identity" and fmt=="p010":
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        checker=spatial.checker
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
        if self.fault=="dimensions" and fmt=="y416":value["output_size"]=[float(size),size]
        if self.fault=="byte-type" and fmt=="y416":value["output_packed_bytes"]=float(value["output_packed_bytes"])
        if self.fault=="input-dimensions" and fmt=="y416":value["input_size"]=[64.0,64]
        if self.fault=="range" and fmt=="y416":value["colour_range"]=2
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name):
        with patch.object(spatial.subprocess,"run",side_effect=self.fake),patch.object(spatial.sys,"stderr",io.StringIO()):
            result=spatial.run(self.binary,self.root/name)
        self.assertEqual(result,json.loads((self.root/name/"y416-spatial-report.json").read_text()));return result

    def test78_jobs_gates_then_native_conversion_then_scaled_conversion(self):
        result=self.execute("complete");self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),78)
        self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:26]));self.assertTrue(result["all_sameformat_p010_gates_complete"])
        self.assertTrue(all(c[6]=="64" for c in self.calls[:52]));self.assertTrue(all(c[6]=="128" for c in self.calls[52:]))
        self.assertEqual(set(result["results"]),{"64","128"})
        for size,cases in result["results"].items():
            self.assertEqual(set(cases),set(spatial.CASES))
            for case,value in cases.items():self.assertTrue(value["repeat_stable"]);self.assertEqual(len(value["repeat_sha256"]),2)

    def test_sameformat_identity_failure_blocks_all_conversion(self):
        self.fault="identity";result=self.execute("identity");self.assertEqual(result["status"],"failed");self.assertEqual(len(self.calls),1)

    def test_metadata_layout_repeat_fail_closed(self):
        for fault in ("dimensions","input-dimensions","byte-type","range","unstable","size"):
            self.fault,self.calls=fault,[];result=self.execute(fault);self.assertEqual(result["status"],"failed",fault)
            self.assertTrue(result["all_sameformat_p010_gates_complete"])


if __name__=="__main__":unittest.main()
