"""Small row-streamed fixtures and fake subprocesses; no GPU."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_y416_large as large


class LargeY416FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_band96_production_parameters_bounds_and_component_isolation(self):
        for case in large.CASES:
            spec=large.case_spec(case)
            if case=="neutral":self.assertIsNone(spec["band_start_native"]);continue
            self.assertEqual(spec["native_band_length"],96);self.assertEqual(spec["band_first_code"],128);self.assertEqual(spec["band_last_code"],888)
            component=spec["component"];axis=spec["axis"];start=spec["band_start_native"]
            for m,value in ((0,128),(start,128),(start+48,512),(start+95,888),(10000,888)):
                self.assertEqual(large.source_code(spec,component,m if axis=="x" else 0,m if axis=="y" else 0),value)
            for c in large.checker.transport.CHANNELS:
                if c!=component:self.assertEqual(large.source_code(spec,c,start,start),512)
            for scale in (1,2):
                window=large.profile_window(spec,1920,1080,scale)
                self.assertEqual(window["margin_output_samples"],32);self.assertGreater(window["stop_output_index_exclusive"],window["start_output_index"])

    def test_stream_generator_matches_small_planes_and_strict_p010_identity(self):
        for case in large.CASES:
            path=self.root/f"{case}.p010";record=large.generate(path,case,128,128);spec=record["case_spec"]
            planes={c:[[large.source_code(spec,c,x,y) for x in range(128 if c=="Y" else 64)]
                       for y in range(128 if c=="Y" else 64)] for c in large.checker.transport.CHANNELS}
            self.assertEqual(path.read_bytes(),large.checker.transport.pack_p010(planes));self.assertTrue(large.p010_identity(path,record,128,128)["exact"])
            self.assertEqual(large.p010_identity(path,record,128,128)["full_code_samples"],128*128*3//2)
        data=bytearray(path.read_bytes());data[-2]|=1;path.write_bytes(data)
        with self.assertRaises(ValueError):large.p010_identity(path,record,128,128)

    def test_rectangular_raw_profiles_histograms_and_no_precision_mask(self):
        path=self.root/"raw.y416";width,height=80,48
        path.write_bytes(b"".join(struct.pack("<4H",100+x,200+y,300+x+y,65281) for y in range(height) for x in range(width)))
        result=large.analyse(path,width,height);positions=result["raw_le16_word_positions"]
        self.assertEqual(positions["0"]["center_row_raw_words"],list(range(100,100+width)))
        self.assertEqual(positions["1"]["center_column_raw_words"],list(range(200,200+height)))
        self.assertEqual(positions["3"]["raw_word_values"],[65281])
        for value in positions.values():
            self.assertEqual(sum(value["low4_histogram"]),width*height);self.assertEqual(sum(value["low6_histogram"]),width*height)
        original=path.read_bytes()
        for bad in (original[:-1],original+b"\x00"):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):large.analyse(path,width,height)


class LargeY416RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.binary=self.root/"fake";self.binary.write_bytes(b"synthetic fakehardware");self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":60,"check":False});self.calls.append(argv)
        iw,ih,ow,oh=map(int,argv[4:8]);copy=argv[8]=="copy";fmt="p010" if copy else argv[14];checker=large.checker
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
        if self.fault=="dimensions" and fmt=="y416":value["output_size"]=[float(ow),oh]
        if self.fault=="metadata" and fmt=="y416":value["colour_range"]=2
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name,neutral_only=False):
        with patch.object(large.subprocess,"run",side_effect=self.fake),patch.object(large.sys,"stderr",io.StringIO()):
            result=large.run(self.binary,self.root/name,128,128,neutral_only=neutral_only)
        self.assertEqual(result,json.loads((self.root/name/"y416-large-report.json").read_text()));return result

    def test42_jobs_all_streamed_native_gates_then_native_and_scaled_y416(self):
        result=self.execute("full");self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),42)
        self.assertEqual(result["case_count"],7);self.assertEqual(result["corpus"],"isolated-ascending")
        self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:14]));self.assertTrue(all(c[6]=="128" for c in self.calls[:28]))
        self.assertTrue(all(c[6]=="256" for c in self.calls[28:]))
        self.assertIn("own_cgroup_memory",result["resources"])
        for cases in result["results"].values():
            for case,value in cases.items():self.assertTrue(value["repeat_stable"])

    def test_explicit_neutral_only_six_job_checkpoint(self):
        result=self.execute("neutral",neutral_only=True);self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),6)
        self.assertEqual(result["case_count"],1);self.assertEqual(result["corpus"],"neutral-only");self.assertEqual(set(result["inputs"]),{"neutral"})
        self.assertTrue(result["all_sameformat_p010_gates_complete"])

    def test_identity_metadata_repeat_size_and_floatshape_fail_closed(self):
        for fault in ("identity","metadata","unstable","size","dimensions"):
            self.fault,self.calls=fault,[];result=self.execute(fault);self.assertEqual(result["status"],"failed",fault)
        self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:14]))

    def test_empty_bandwindow_blocks_gpu_before_input_generation(self):
        with patch.object(large.subprocess,"run",side_effect=self.fake):result=large.run(self.binary,self.root/"small",64,64)
        self.assertEqual(result["status"],"failed");self.assertEqual(self.calls,[])


if __name__=="__main__":unittest.main()
