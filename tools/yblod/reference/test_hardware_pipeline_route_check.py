"""Fake hardware only; pipeline hint is not an engine guarantee."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware_pipeline_route_check as checker
from scaling_probe import CHANNELS,pack_p010,unpack_p010


class PipelineRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.binary=self.root/"fake"
        self.binary.write_bytes(b"synthetic fake, not hardware")
        self.calls,self.fault=[],None

    def fake(self,argv,**kwargs):
        self.assertEqual(kwargs,{"capture_output":True,"timeout":60,"check":False})
        self.calls.append(argv)
        iw,ih,ow,oh=map(int,argv[4:8]);copy=argv[8]=="copy"
        route="default" if copy else argv[14]
        if iw==ow:shutil.copyfile(argv[2],argv[3])
        else:
            source=unpack_p010(Path(argv[2]).read_bytes(),iw,ih)
            output={c:[[source[c][y//2][x//2] for x in range(ow if c=="Y" else ow//2)]
                       for y in range(oh if c=="Y" else oh//2)] for c in CHANNELS}
            if self.fault=="different-routes" and route=="fast" and "channel-tags" not in argv[2]:output["Y"][0][0]+=1
            Path(argv[3]).write_bytes(pack_p010(output))
        if self.fault=="fast-native" and route=="fast" and iw==ow:
            data=bytearray(Path(argv[3]).read_bytes());data[:2]=(513<<6).to_bytes(2,"little");Path(argv[3]).write_bytes(data)
        if self.fault=="lowbits":
            data=bytearray(Path(argv[3]).read_bytes());data[0]|=1;Path(argv[3]).write_bytes(data)
        value={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete","vendor":"synthetic fake",
               "va_version":[1,24],"input_size":[iw,ih],"output_size":[ow,oh],"filter_flags":0,
               "input_chroma_siting":None if copy else 6,"output_chroma_siting":None if copy else 6,
               "colour_standard":None if copy else 12,"colour_range":None if copy else 2,
               "vpp_submitted":not copy,"hardware_engine_verified":False,
               "pipeline_flags":None if copy else checker.ROUTES[route],"pipeline_caps_flags":None if copy else 2,
               "drm_client_engine_accounting":{"synthetic":True}}
        if self.fault=="unadvertised" and route=="fast":value["pipeline_caps_flags"]=0
        if self.fault=="wrong-bit" and route=="fast":value["pipeline_flags"]=1
        if self.fault=="missing":value.pop("pipeline_caps_flags")
        if self.fault=="unsupported" and route=="fast":return subprocess.CompletedProcess(argv,1,b"",b"unsupported, no fallback")
        if self.fault=="timeout":raise subprocess.TimeoutExpired(argv,60,output=b"partial")
        return subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b"fake diagnostics")

    def execute(self,name):
        stderr=io.StringIO()
        with patch.object(checker.subprocess,"run",side_effect=self.fake),patch.object(checker.sys,"stderr",stderr):
            report=checker.run(self.binary,self.root/name,64,64)
        self.assertEqual(report,json.loads((self.root/name/"pipeline-route-report.json").read_text()))
        return report,stderr.getvalue()

    def test49_jobs_all_native_first_confirmed_flag2_payload_preserved(self):
        report,progress=self.execute("complete")
        self.assertEqual(report["status"],"complete")
        self.assertEqual(len(self.calls),49)
        self.assertTrue(all(int(c[6])==64 for c in self.calls[:21]))
        self.assertTrue(all(int(c[6])==128 for c in self.calls[21:]))
        self.assertTrue(report["all_native_route_gates_complete"])
        self.assertEqual(report["pipeline_hints"]["fast"],2)
        self.assertTrue(all(v["equal"] for v in report["route_hash_comparison"].values()))
        self.assertIn("route scaled complete fast",progress)
        self.assertIn("drm_client_engine_accounting",report["invocations"][-1]["invocation"])

    def test_fast_native_failure_blocks_every_2x(self):
        self.fault="fast-native"
        report,_=self.execute("identity")
        self.assertEqual(report["status"],"failed")
        self.assertTrue(all(int(c[6])==64 for c in self.calls))

    def test_unsupported_unadvertised_wrong_bit_missing_lowbits_timeout_fail_closed(self):
        for fault in ("unsupported","unadvertised","wrong-bit","missing","lowbits","timeout"):
            self.fault,self.calls=fault,[]
            report,_=self.execute(fault)
            self.assertEqual(report["status"],"failed",fault)
            self.assertTrue(all(int(c[6])==64 for c in self.calls))
            self.assertIn("stdout",report["invocations"][-1])
            self.assertIn("stderr",report["invocations"][-1])

    def test_route_hash_difference_is_diagnostic_not_gate(self):
        self.fault="different-routes"
        report,_=self.execute("difference")
        self.assertEqual(report["status"],"complete")
        self.assertFalse(report["route_hash_comparison"]["x-8"]["equal"])


if __name__=="__main__":unittest.main()
