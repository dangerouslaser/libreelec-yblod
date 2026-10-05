"""Exact independent per-pass oracle and fake hardware only."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_scaling_controls as controls
import scaling_oracle
from scaling_probe import CHANNELS, pack_p010, unpack_p010


class ControlsOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def planes(self, pattern, offset, width=64, height=64):
        return {c: [[controls.source_code(pattern,c,x,y,width,height,offset)
                     for x in range(width if c=="Y" else width//2)]
                    for y in range(height if c=="Y" else height//2)] for c in CHANNELS}

    def test_signed_ramps_every_base_and_component_against_two_pass_fraction_oracle(self):
        for pattern, offset in controls.CASES:
            if pattern=="channel-tags": continue
            axis = pattern[0]
            for c in CHANNELS:
                extent = 192 if c=="Y" else 96
                values = [controls.source_code(pattern,c,m if axis=="x" else 0,m if axis=="y" else 0,192,192,offset)
                          for m in range(extent)]
                output,_,_ = scaling_oracle.expand([values] if axis=="x" else [[v] for v in values],c)
                start,length,_,_ = controls.band(pattern,c,192,192)
                self.assertEqual(length,96)
                self.assertGreaterEqual(min(values),128)
                self.assertLessEqual(max(values),890)
                for m in range(start*2+16,(start+length)*2-16):
                    self.assertEqual(output[0][m] if axis=="x" else output[m][0],
                                     controls.expected_code(pattern,c,m if axis=="x" else 0,m if axis=="y" else 0,192,192,2,offset),
                                     (pattern,offset,c,m))

    def test_stream_generation_scan_and_all_frame_covariance(self):
        for pattern,offset in controls.CASES:
            path = self.root/f"{pattern}-{offset}.p010"
            record = controls.generate(path,pattern,offset,64,64)
            self.assertEqual(path.read_bytes(),pack_p010(self.planes(pattern,offset)))
            score = controls.scan(path,pattern,offset,64,64,1)
            self.assertEqual(record["sha256"],score["sha256"])
            self.assertTrue(all(c["different"]==0 for c in score["channels"].values()))
            if offset:
                comparison = controls.compare_offsets(self.root/f"{pattern}-0.p010",path,pattern,offset,64,64,1)
                self.assertTrue(all(c["full"]["different"]==0 for c in comparison["channels"].values()))

    def test_covariance_detects_full_frame_and_band_errors_without_correcting(self):
        pattern="x-8"
        a,b = self.root/"a.p010",self.root/"b.p010"
        controls.generate(a,pattern,0,64,64)
        controls.generate(b,pattern,1,64,64)
        planes=unpack_p010(b.read_bytes(),64,64)
        planes["Y"][20][20]+=3
        b.write_bytes(pack_p010(planes))
        score=controls.compare_offsets(a,b,pattern,1,64,64,1)
        self.assertEqual(score["channels"]["Y"]["full"]["different"],1)
        self.assertEqual(score["channels"]["Y"]["interior"]["sum_signed_error"],3)
        self.assertEqual(score["channels"]["Y"]["full"]["maximum_absolute_error"],3)
        bad=bytearray(b.read_bytes());bad[0]|=1;b.write_bytes(bad)
        with self.assertRaises(ValueError): controls.compare_offsets(a,b,pattern,1,64,64,1)

    def test_scan_rejects_truncation_padding_and_lowbits_everywhere(self):
        path=self.root/"input.p010"
        controls.generate(path,"y-2",0,64,64)
        original=path.read_bytes()
        for bad in (original[:-1],original+b"\x00",original[:-2]+bytes([original[-2]|1])+original[-1:]):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):controls.scan(path,"y-2",0,64,64,1)


class ControlsRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.binary=self.root/"fake"
        self.binary.write_bytes(b"synthetic fake hardware")
        self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":60,"check":False})
        self.calls.append(argv)
        iw,ih,ow,oh=map(int,argv[4:8]);mode=argv[8];copy=mode=="copy"
        if iw==ow:shutil.copyfile(argv[2],argv[3])
        else:
            source=unpack_p010(Path(argv[2]).read_bytes(),iw,ih)
            output={c:[[source[c][y//2][x//2] for x in range(ow if c=="Y" else ow//2)]
                       for y in range(oh if c=="Y" else oh//2)] for c in CHANNELS}
            if self.fault=="different-modes" and mode=="fast" and "channel-tags" not in argv[2]:output["Y"][0][0]+=1
            Path(argv[3]).write_bytes(pack_p010(output))
        if self.fault in ("fast-native","hq-native") and mode==self.fault.split("-")[0] and iw==ow:
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        if self.fault=="lowbits":
            data=bytearray(Path(argv[3]).read_bytes());data[0]|=1;Path(argv[3]).write_bytes(data)
        value={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete","vendor":"synthetic fake",
               "va_version":[1,24],"input_size":[iw,ih],"output_size":[ow,oh],"filter_flags":0 if copy else controls.FLAGS[mode],
               "input_chroma_siting":None if copy else 6,"output_chroma_siting":None if copy else 6,
               "colour_standard":None if copy else 12,"colour_range":None if copy else 2,
               "vpp_submitted":not copy,"hardware_engine_verified":False,"drm_client_engine_accounting":{"synthetic":True}}
        if self.fault=="flags" and not copy:value["filter_flags"]=1
        if self.fault=="dimensions":value["input_size"]=[float(iw),ih]
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name):
        progress=io.StringIO()
        with patch.object(controls.subprocess,"run",side_effect=self.fake),patch.object(controls.sys,"stderr",progress):
            result=controls.run(self.binary,self.root/name,64,64)
        self.assertEqual(result,json.loads((self.root/name/"controls-report.json").read_text()))
        return result,progress.getvalue()

    def test190_jobs_every_native_mode_before_all_scaled_with_covariance(self):
        report,progress=self.execute("complete")
        self.assertEqual(report["status"],"complete")
        self.assertEqual(len(self.calls),190)
        self.assertTrue(all(int(c[6])==64 for c in self.calls[:76]))
        self.assertTrue(all(int(c[6])==128 for c in self.calls[76:]))
        self.assertTrue(report["all_native_quality_gates_complete"])
        self.assertTrue(all(c["all_equal"] for c in report["mode_hash_comparison"].values()))
        self.assertIn("native complete hq",progress)
        self.assertIn("scaled complete fast",progress)
        for mode in controls.FLAGS:
            for case,v in report["results"][mode].items():
                self.assertTrue(v["repeat_stable"])
                if case.endswith(("base1","base2")):
                    self.assertTrue(all(c["full"]["different"]==0 for c in v["base_offset_covariance"]["channels"].values()))
        self.assertIn("drm_client_engine_accounting",report["invocations"][-1]["invocation"])

    def test_fast_and_hq_native_failure_blocks_every_2x(self):
        for fault in ("fast-native","hq-native"):
            self.fault,self.calls=fault,[]
            report,_=self.execute(fault)
            self.assertEqual(report["status"],"failed")
            self.assertTrue(all(int(c[6])==64 for c in self.calls))
            self.assertNotIn("all_native_quality_gates_complete",report)

    def test_mode_output_equality_is_diagnostic_not_gate(self):
        self.fault="different-modes"
        report,_=self.execute("modes")
        self.assertEqual(report["status"],"complete")
        self.assertFalse(report["mode_hash_comparison"]["x-8-base0"]["all_equal"])

    def test_bad_flags_dimensions_lowbits_fail_before_scaling(self):
        for fault in ("flags","dimensions","lowbits"):
            self.fault,self.calls=fault,[]
            report,_=self.execute(fault)
            self.assertEqual(report["status"],"failed")
            self.assertTrue(all(int(c[6])==64 for c in self.calls))


if __name__=="__main__":unittest.main()
