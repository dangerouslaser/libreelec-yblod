import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import hardware_y416_neutral as neutral
import test_hardware_y416_large as legacy


class NeutralY416Tests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.binary=self.root/"fake"
        self.binary.write_bytes(b"synthetic fake probe");self.calls=[];self.fault=None

    def fake(self,argv,**kwargs):
        result=legacy.LargeY416RunnerTests.fake(self,argv,**kwargs)
        if self.fault=="last-native" and argv[8]=="default" and "Cr-x-stripe-plus" in argv[3] and argv[3].endswith(".p010"):
            path=Path(argv[3]);raw=bytearray(path.read_bytes());raw[:2]=(513<<6).to_bytes(2,"little");path.write_bytes(raw)
        return result

    def run_fake(self,name="run",**kwargs):
        with mock.patch.object(neutral.subprocess,"run",side_effect=self.fake),mock.patch.object(neutral.sys,"stderr",io.StringIO()):
            return neutral.run(self.binary,self.root/name,**kwargs)

    def test_generator_exact_source_planes_and_signs(self):
        cases=neutral.CASES+tuple(f"{c}-{axis}-{kind}-{sign}" for c in ("Y","Cb","Cr") for axis in ("x","y") for kind in ("step","stripe","stair") for sign in ("plus","minus"))
        for index,case in enumerate(cases):
            path=self.root/f"{index}.p010";record=neutral.generate(path,case);spec=record["case_spec"]
            planes={c:[[neutral.source_code(spec,c,x,y) for x in range(64 if c=="Y" else 32)] for y in range(64 if c=="Y" else 32)] for c in ("Y","Cb","Cr")}
            self.assertEqual(path.read_bytes(),neutral.large.checker.transport.pack_p010(planes))
            self.assertTrue(neutral.large.p010_identity(path,record,64,64)["exact"])
            self.assertTrue(all(v in (511,512,513) for rows in planes.values() for row in rows for v in row))

    def test_all24_jobs_native_gates_before_any_y416_repeats_stable(self):
        report=self.run_fake()
        self.assertEqual(report["status"],"complete");self.assertEqual(len(self.calls),24)
        self.assertTrue(all(v[3].endswith(".p010") for v in self.calls[:8]))
        self.assertTrue(all(v[6]=="64" for v in self.calls[8:16]))
        self.assertTrue(all(v[6]=="128" for v in self.calls[16:]))
        self.assertTrue(report["all_sameformat_p010_gates_complete"])
        self.assertEqual(report["planned_raw_bytes"],1458176)
        self.assertLess(report["planned_raw_bytes"],2*1024*1024)
        self.assertEqual(report,json.loads((self.root/"run/y416-neutral-report.json").read_text()))

    def test_late_native_gate_failure_blocks_every_y416_submission(self):
        self.fault="last-native";report=self.run_fake()
        self.assertEqual(report["status"],"failed");self.assertEqual(len(self.calls),8)
        self.assertTrue(all(v[3].endswith(".p010") for v in self.calls))

    def test_probe_metadata_repeat_size_fail_closed(self):
        for fault in ("metadata","unstable","size","dimensions"):
            self.calls=[];self.fault=fault;report=self.run_fake(fault)
            self.assertEqual(report["status"],"failed",fault)
            self.assertIn("error",report)

    def test_subhalf_raw_word_counts_preserve_signed_values_ignore_alpha(self):
        path=self.root/"words.y416"
        raw=b"".join(struct.pack("<4H",32768+d,32768-d,32768,32769) for d in (-33,-32,-1,0,1,32,33))
        path.write_bytes(raw);result=neutral.near_neutral(path,7,1)
        self.assertEqual(result["Cb"]["raw_delta_histogram"],[dict(delta=v,count=1) for v in (-32,-1,1,32)])
        self.assertEqual(result["Y"]["nonzero_within_half_native_code_count"],4)
        self.assertEqual(result["Cr"]["nonzero_within_half_native_code_count"],0)
        self.assertNotIn("alpha",result)

    def test_large_cohort_preflight_rejects_before_destination_or_gpu(self):
        with self.assertRaisesRegex(ValueError,"300MiB"):
            neutral.run(self.binary,self.root/"too-large",1920,1080)
        self.assertFalse((self.root/"too-large").exists());self.assertEqual(self.calls,[])
        for kwargs in (dict(repeats=True),dict(cases="neutral"),dict(native_y416=1)):
            with self.assertRaises(ValueError):neutral.run(self.binary,self.root/"invalid",**kwargs)


if __name__=="__main__":unittest.main()
