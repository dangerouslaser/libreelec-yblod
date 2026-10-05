"""Synthetic raw-word format hypotheses and fake conversion subprocesses."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_y416_check as checker


class Y416AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def frame(self,path,words):
        path.write_bytes(struct.pack("<4H",*words)*(64*64))

    def test_raw_word_indices_identify_uyva_distinct_tags_without_assuming(self):
        codes=checker.native_codes("channel-tags");path=self.root/"tags.y416"
        self.frame(path,(codes["Cb"]*64,codes["Y"]*64,codes["Cr"]*64,65535))
        result=checker.analyse(path,codes)
        self.assertTrue(result["mapping_hypotheses"]["UYVA"]["native_code_scale_hypotheses"]["64"]["all_color_words_match"])
        self.assertFalse(result["mapping_hypotheses"]["AVYU"]["native_code_scale_hypotheses"]["64"]["all_color_words_match"])
        self.assertTrue(result["mapping_hypotheses"]["UYVA"]["alpha_all_65535"])
        self.assertEqual(result["raw_le16_word_positions"]["0"]["raw_word_values"],[384*64])

    def test_alternate_order_is_measured_not_rejected(self):
        codes=checker.native_codes("channel-tags");path=self.root/"alternate.y416"
        self.frame(path,(65535,codes["Cr"]*16,codes["Y"]*16,codes["Cb"]*16))
        result=checker.analyse(path,codes)
        self.assertTrue(result["mapping_hypotheses"]["AVYU"]["native_code_scale_hypotheses"]["16"]["all_color_words_match"])
        self.assertTrue(result["mapping_hypotheses"]["AVYU"]["alpha_all_65535"])

    def test_nonzero_low4_low6_and_alpha_are_preserved_not_stripped(self):
        path=self.root/"raw.y416"
        self.frame(path,(65,32769,65473,7))
        result=checker.analyse(path,checker.native_codes("code-512"))
        for index,word in enumerate((65,32769,65473,7)):
            stats=result["raw_le16_word_positions"][str(index)]
            self.assertEqual(stats["raw_word_values"],[word])
            self.assertEqual(stats["low4_histogram"][word&15],4096)
            self.assertEqual(stats["low6_histogram"][word&63],4096)
            self.assertEqual(sum(stats["low6_histogram"]),4096)
        self.assertFalse(result["mapping_hypotheses"]["UYVA"]["alpha_all_65535"])

    def test_exact_length_enforced_and_geometry_bounded(self):
        path=self.root/"bad.y416"
        self.frame(path,(0,0,0,65535));data=path.read_bytes()
        for bad in (data[:-1],data+b"\x00"):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):checker.analyse(path,checker.native_codes("code-0"))
        with self.assertRaises(ValueError):checker.input_planes("code-0",256,64)


class Y416RunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.binary=self.root/"fake"
        self.binary.write_bytes(b"synthetic fake hardware")
        self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":30,"check":False})
        self.calls.append(argv)
        width,height=map(int,argv[4:6]);copy=argv[8]=="copy"
        fmt="p010" if copy else argv[14];range_name="full" if copy else argv[16]
        if fmt=="p010":shutil.copyfile(argv[2],argv[3])
        else:
            planes=checker.transport.unpack_p010(Path(argv[2]).read_bytes(),width,height)
            # Fake <<6 coding, intentionally never nominal-range clamped.
            words=(planes["Cb"][0][0]*64,planes["Y"][0][0]*64,planes["Cr"][0][0]*64,65535)
            if self.fault=="lowbits":words=tuple(v+1 if i<3 else v for i,v in enumerate(words))
            if self.fault=="unstable" and argv[3].endswith("-1.y416"):words=(words[0],words[1]+1,words[2],words[3])
            data=struct.pack("<4H",*words)*(width*height)
            if self.fault=="size":data=data[:-1]
            Path(argv[3]).write_bytes(data)
        if self.fault=="identity" and fmt=="p010":
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        value={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete","vendor":"synthetic fake","va_version":[1,24],
               "input_size":[width,height],"output_size":[width,height],"filter_flags":0,
               "input_fourcc":checker.FOURCC["p010"],"output_fourcc":checker.FOURCC[fmt],
               "input_rt_format":checker.RT_FORMAT["p010"],"output_rt_format":checker.RT_FORMAT[fmt],
               "output_packed_bytes":width*height*(3 if fmt=="p010" else 8),
               "input_chroma_siting":None if copy else 6,"output_chroma_siting":None if copy else (6 if fmt=="p010" else 0),
               "colour_standard":None if copy else 12,"colour_range":None if copy else checker.RANGES[range_name],
               "pipeline_flags":None if copy else 0,"pipeline_caps_flags":None if copy else 2,
               "vpp_submitted":not copy,"hardware_engine_verified":False,"drm_client_engine_accounting":{"synthetic":True}}
        if self.fault=="rt" and fmt=="y416":value["output_rt_format"]=0x100
        if self.fault=="fourcc" and fmt=="y416":value["output_fourcc"]=checker.FOURCC["p010"]
        if self.fault=="range" and fmt=="y416":value["colour_range"]=0
        if self.fault=="dimensions" and fmt=="y416":value["input_size"]=[float(width),height]
        if self.fault=="output-dimensions" and fmt=="y416":value["output_size"]=[width,float(height)]
        if self.fault=="unsupported" and fmt=="y416":return subprocess.CompletedProcess(argv,1,b"",b"unsupported, no fallback")
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name):
        with patch.object(checker.subprocess,"run",side_effect=self.fake),patch.object(checker.sys,"stderr",io.StringIO()):
            result=checker.run(self.binary,self.root/name)
        self.assertEqual(result,json.loads((self.root/name/"y416-report.json").read_text()))
        return result

    def test72_jobs_all24_sameformat_gates_before_conversion(self):
        result=self.execute("complete")
        self.assertEqual(result["status"],"complete");self.assertEqual(len(self.calls),72)
        self.assertTrue(all(c[3].endswith(".p010") for c in self.calls[:24]))
        self.assertTrue(all(c[3].endswith(".y416") for c in self.calls[24:]))
        self.assertTrue(result["all_sameformat_p010_gates_complete"])
        self.assertTrue(all(v["equal"] for v in result["range_hash_comparison"].values()))
        raw=result["results"]["reduced"]["code-1023"]["raw_le16_word_positions"]["1"]["raw_word_values"]
        self.assertEqual(raw,[1023*64])  # reduced flags don't assume a clamp
        self.assertIn("drm_client_engine_accounting",result["invocations"][-1]["invocation"])

    def test_identity_gate_prevents_every_format_conversion(self):
        self.fault="identity";result=self.execute("identity")
        self.assertEqual(result["status"],"failed");self.assertEqual(len(self.calls),1)

    def test_lowbits_not_rejected_for_y416(self):
        self.fault="lowbits";result=self.execute("lowbits")
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["results"]["full"]["code-0"]["raw_le16_word_positions"]["1"]["raw_word_values"],[1])

    def test_format_metadata_failure_repetition_and_size_fail_closed(self):
        for fault in ("rt","fourcc","range","dimensions","output-dimensions","unsupported","unstable","size"):
            self.fault,self.calls=fault,[];result=self.execute(fault)
            self.assertEqual(result["status"],"failed",fault)
            self.assertTrue(result["all_sameformat_p010_gates_complete"])
            self.assertIn("stderr",result["invocations"][-1])


if __name__=="__main__":unittest.main()
