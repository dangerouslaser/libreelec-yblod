"""Independent synthetic fixtures; actual-header executable or pinned archive.

Set YB_DOVI_ADAPTER_PROBE to execute the real C smoke. Otherwise replay the
published synthetic checkpoint when available; never fabricate execution.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

import reference

ROOT=Path(__file__).resolve().parent
SOURCES=("native_dovi_adapter.c", "native_dovi_adapter.h", "native_dovi_adapter_probe.c",
         "native_composer.c", "native_composer.h")
HEADER_SHA="f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02"
LIBAVUTIL_SHA="16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108"
BINARY_SHA="4a0090f47d336420f126a6beb122c88918622b9358d1e1fa7557bbd9da8544b9"
UBSAN_BINARY_SHA="4cbb9bbdcbf5b8475e7208f05809ae1f278f109584de116d3993181dd13d7974"
UBSAN_RUNTIME_SHA="429866ada58bdd88bd5e50e4d20ddc35c6e4d3e96101b1886da9e94deb4ae323"
ARCHIVE=ROOT/"results/native-dovi-adapter-cpu-20261005b.json"
INSTRUCTIONS_BYTES=9216  # Observed from the reviewed GCC16.2/actual-header SDK build.
ACCEPTED=("baseline", "negative-coefficient", "cumulative-pivots", "mmr1", "mmr2", "mmr3",
          "poisoned-inactive", "disabled-poisoned-nlq", "disabled-denominator13", "depth8", "spatial-flags", "empty-ext-at-end")
REJECTED={"float-coefficients":3,"explicit-chroma-filter":7,"invalid-chroma-flag":3,"unknown-header":3,
          "unsupported-depth":3,"multiple-partitions":4,"unknown-method":4,"mmr-luma":4,"bad-nlq-method":5,
          "wrong-nlq-pivots":5,"late-offset-overflow":5,"late-coefficient-overflow":4,"duplicate-pivots":4,
          "truncated":1,"offset-wrap":2,"overlap-regions":2,"overlap-prefix":2,"overlap-ext":2,
          "bad-ext-stride":2,"negative-ext-count":2,"output-alias":6,"address-wrap":1,
          "null-input":1,"null-output":1,"misaligned-input":1,"misaligned-output":1,"wrapping-output":1,"oversized-bytes":1}
CASES=ACCEPTED+tuple(REJECTED)


def same(a,b):
    return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)


def expected_configuration(name):
    depth=8 if name=="depth8" else 10
    denominator=13 if name=="disabled-denominator13" else 23
    enabled=name not in ("disabled-poisoned-nlq","disabled-denominator13")
    maximum=(1<<depth)-1
    mappings=[]
    for component in range(3):
        curve=dict(pivots=[0,maximum],segments=[dict(method="polynomial",coefficients=[0,1<<denominator])])
        if name=="negative-coefficient": curve["segments"][0]["coefficients"][0]=-8185
        if name=="cumulative-pivots":
            curve["pivots"]=[0,400,1023]
            curve["segments"].append(dict(method="polynomial",coefficients=[7,1<<22,1<<21]))
        if component and name in ("mmr1","mmr2","mmr3"):
            order=int(name[-1])
            curve["segments"]=[dict(method="mmr",constant=1<<21,
                coefficients=[[(term+1)*8192*(-1 if row%2 else 1) for term in range(7)] for row in range(order)])]
        mappings.append(curve)
    nlq=[dict(bit_depth=depth,denominator=denominator,offset=1<<(depth-1),slope=2048,threshold=0,maximum=1025) if enabled else
         dict(bit_depth=0,denominator=0,offset=0,slope=0,threshold=0,maximum=0) for _ in range(3)]
    return dict(bit_depth=depth,denominator=denominator,output_depth=12,enabled=enabled,
                spatial_flags=[1,1] if name=="spatial-flags" else [0,0],mappings=mappings,nlq=nlq)


def validate_case(record,name):
    if (type(record) is not dict or record.get("schema")!="yblod.native-dovi-adapter-case.v1" or record.get("case")!=name
            or type(record.get("status")) is not int or type(record.get("abi_version")) is not int
            or record["abi_version"]!=1 or type(record.get("instructions_bytes")) is not int
            or record["instructions_bytes"]!=INSTRUCTIONS_BYTES or record.get("input_unchanged") is not True):
        raise ValueError("invalid native case identity or type")
    status=0 if name in ACCEPTED else REJECTED[name]
    if record["status"]!=status: raise ValueError("unexpected adapter result")
    keys={"schema","case","status","abi_version","instructions_bytes","input_unchanged","failure_output_untouched"}
    if not status:
        keys.update(("canonical_unused","source_released_before_arithmetic","configuration","sample_triplet","el_sample","stages"))
    if set(record)!=keys: raise ValueError("unexpected case fields")
    if status:
        if record.get("failure_output_untouched") is not True or any(k in record for k in ("configuration","stages")):
            raise ValueError("failed adapter published changed output")
        return
    if (record.get("failure_output_untouched") is not False or record.get("canonical_unused") is not True
            or record.get("source_released_before_arithmetic") is not True):
        raise ValueError("missing copy/canonical ownership proof")
    expected=expected_configuration(name)
    if not same(record.get("configuration"),expected): raise ValueError("integer metadata translation mismatch")
    samples=[128,64,32] if expected["bit_depth"]==8 else [512,256,128]
    el=(1<<(expected["bit_depth"]-1))-2
    if not same(record.get("sample_triplet"),samples) or type(record.get("el_sample")) is not int or record["el_sample"]!=el:
        raise ValueError("synthetic sample mismatch")
    stages=[]
    for component in range(3):
        mapped=reference.map_sample(component,samples,expected["mappings"],expected["bit_depth"],expected["denominator"])
        residual=reference.inverse_el(el,expected["nlq"][component],expected["bit_depth"],expected["denominator"]) if expected["enabled"] else 0
        stages.append([mapped,residual,mapped+residual,reference.reconstruct(mapped,residual,12)])
    if not same(record.get("stages"),stages): raise ValueError("independent integer stages differ")


def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError("duplicate key")
            out[key]=value
        return out
    def invalid(value): raise ValueError("nonfinite JSON")
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid,parse_float=invalid)


def load_archive(path):
    path=Path(path)
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(descriptor,"rb") as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size>1024**2: raise ValueError("bounded regular checkpoint required")
        raw=stream.read(1024**2+1)
        snapshot=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if (len(raw)!=before.st_size or len(raw)>1024**2 or snapshot(os.fstat(stream.fileno()))!=snapshot(before)
                or snapshot(path.stat())!=snapshot(before)): raise ValueError("checkpoint changed")
    report=strict_json(raw)
    if (type(report) is not dict or report.get("schema")!="yblod.native-dovi-adapter-cohort.v1" or report.get("status")!="complete"
            or report.get("synthetic_only") is not True or report.get("gpu_attempted") is not False
            or report.get("header_sha256")!=HEADER_SHA or type(report.get("cases")) is not list
            or any(type(item) is not dict for item in report["cases"])
            or [item.get("case") for item in report["cases"]]!=list(CASES)):
        raise ValueError("unexpected checkpoint identity")
    keys={"accepted_per_build","analysis_pin_scope","analysis_sha256","binary_sha256","case_evidence","cases",
          "cohort_script_sha256","excluded_runs","gpu_attempted","header_sha256","libavutil_sha256","memory",
          "normal_cases","rejected_per_build","runtime_library_hash_lists_unchanged","sanitizer_cases","schema",
          "scope","source_sha256","status","synthetic_only","ubsan"}
    if set(report)!=keys: raise ValueError("unexpected checkpoint fields")
    for key,value in (("normal_cases",40),("sanitizer_cases",40),("accepted_per_build",12),("rejected_per_build",28)):
        if type(report.get(key)) is not int or report[key]!=value: raise ValueError("invalid cohort count")
    if report.get("runtime_library_hash_lists_unchanged") is not True:
        raise ValueError("runtime library identity changed")
    pins={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}
    if report.get("source_sha256")!=pins: raise ValueError("checkpoint source pins differ")
    for field in ("binary_sha256","libavutil_sha256"):
        value=report.get(field)
        if type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid artifact digest")
    if report["libavutil_sha256"] != LIBAVUTIL_SHA or report["binary_sha256"]!=BINARY_SHA:
        raise ValueError("checkpoint binary/library differs")
    script=ROOT/"run_native_dovi_adapter_probe.sh"
    if report.get("cohort_script_sha256")!=hashlib.sha256(script.read_bytes()).hexdigest():
        raise ValueError("cohort script differs")
    ubsan=report.get("ubsan")
    expected_ubsan=dict(binary_sha256=UBSAN_BINARY_SHA,runtime_sha256=UBSAN_RUNTIME_SHA,
                        cases=40,diagnostics_empty=True,all_stdout_byte_exact=True)
    if not same(ubsan,expected_ubsan): raise ValueError("sanitizer evidence differs")
    evidence=report.get("case_evidence")
    if type(evidence) is not list or len(evidence)!=len(CASES): raise ValueError("missing case evidence")
    empty_sha=hashlib.sha256(b"").hexdigest()
    for record,name in zip(evidence,CASES):
        if type(record) is not dict or record.get("case")!=name: raise ValueError("case evidence identity differs")
        for key in ("normal_exit_status","ubsan_exit_status"):
            if type(record.get(key)) is not int or record[key]!=0: raise ValueError("case execution failed")
        a,b=record.get("normal_stdout_sha256"),record.get("ubsan_stdout_sha256")
        if type(a) is not str or len(a)!=64 or any(c not in "0123456789abcdef" for c in a) or b!=a:
            raise ValueError("normal/sanitizer outputs differ")
        if any(record.get(key)!=empty_sha for key in ("normal_stderr_sha256","ubsan_stderr_sha256")):
            raise ValueError("case diagnostics were not empty")
    memory=report.get("memory")
    if type(memory) is not dict: raise ValueError("memory observation required")
    for field,value in (("max_bytes",512*1024**2),("swap_max_bytes",0),
                        ("swap_current_before_bytes",0),("swap_current_after_bytes",0)):
        if type(memory.get(field)) is not int or memory[field]!=value: raise ValueError("memory/swap scope differs")
    peak=memory.get("peak_observed_before_exit_bytes")
    if type(peak) is not int or not 0<=peak<=512*1024**2: raise ValueError("invalid memory snapshot")
    for field in ("events_before","events_after"):
        events=memory.get(field)
        if type(events) is not dict or any(type(events.get(k)) is not int or events[k]!=0 for k in ("max","oom","oom_kill")):
            raise ValueError("memory pressure/oom event observed")
    for item,name in zip(report["cases"],CASES): validate_case(item,name)
    return report["cases"]


class OracleTests(unittest.TestCase):
    def test_literal_negative_cap_and_fractional_coefficient(self):
        config=expected_configuration("baseline")
        self.assertEqual(reference.inverse_el(510,config["nlq"][0],10,23),-9)
        self.assertEqual(reference.reconstruct(32768,-9,12),2047)
        negative=expected_configuration("negative-coefficient")
        self.assertEqual(-1*(1<<23)+((1<<23)-8185),-8185)
        self.assertEqual(reference.map_sample(0,[512,256,128],negative["mappings"],10,23),32704)

    def test_fixed_case_names_and_source_inventory(self):
        self.assertEqual(len(CASES),40);self.assertEqual(len(set(CASES)),40)
        for name in CASES: self.assertIn('"'+name+'"',(ROOT/"native_dovi_adapter_probe.c").read_text())
        for name in SOURCES: self.assertTrue((ROOT/name).is_file())

    def test_archive_parser_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"report.json"
            for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1.0}',b'[]',b'false',b'{"schema":"wrong"}',b' '*(1024**2+1)):
                path.write_bytes(raw)
                with self.assertRaises((ValueError,KeyError)): load_archive(path)


class ActualAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=os.environ.get("YB_DOVI_ADAPTER_PROBE")
        if binary:
            path=Path(binary).resolve(strict=True);before=hashlib.sha256(path.read_bytes()).hexdigest();cls.records=[]
            for name in CASES:
                result=subprocess.run([str(path),name],capture_output=True,timeout=15)
                if result.returncode or result.stderr or len(result.stdout)>1024**2: raise AssertionError("probe execution failed or emitted diagnostics")
                item=strict_json(result.stdout);validate_case(item,name);cls.records.append(item)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=before: raise AssertionError("probe changed")
        else:
            path=Path(os.environ.get("YB_DOVI_ADAPTER_REPORT",ARCHIVE))
            if not path.exists(): raise unittest.SkipTest("actual-header C probe/checkpoint not available")
            cls.records=load_archive(path)

    def test_every_fixed_fixture(self):
        for record,name in zip(self.records,CASES): validate_case(record,name)

    def test_poisoned_inactive_and_disabled_fields(self):
        records={item["case"]:item for item in self.records}
        self.assertEqual(records["poisoned-inactive"]["configuration"],records["baseline"]["configuration"])
        self.assertFalse(records["disabled-poisoned-nlq"]["configuration"]["enabled"])
        self.assertEqual(records["disabled-denominator13"]["configuration"]["denominator"],13)

    def test_rejections_preserve_output(self):
        for item in self.records:
            if item["case"] in REJECTED:
                self.assertIs(item["failure_output_untouched"],True)
                self.assertIs(item["input_unchanged"],True)

    def test_record_tampering_and_boolean_type_confusion(self):
        accepted=copy.deepcopy(self.records[0]);accepted["status"]=False
        with self.assertRaises(ValueError): validate_case(accepted,"baseline")
        accepted=copy.deepcopy(self.records[0]);accepted["configuration"]["mappings"][0]["pivots"][0]=False
        with self.assertRaises(ValueError): validate_case(accepted,"baseline")
        accepted=copy.deepcopy(self.records[0]);accepted["stages"][0][1]+=1
        with self.assertRaises(ValueError): validate_case(accepted,"baseline")
        accepted=copy.deepcopy(self.records[0]);accepted["private_path"]="unexpected"
        with self.assertRaises(ValueError): validate_case(accepted,"baseline")

    def test_checkpoint_provenance_resource_and_log_tampering(self):
        if not ARCHIVE.exists(): self.skipTest("published checkpoint not available")
        original=strict_json(ARCHIVE.read_bytes())
        changes=[(("private_path",),"unexpected"),(("normal_cases",),True),
                 (("runtime_library_hash_lists_unchanged",),1),
                 (("binary_sha256",),"0"*64),(("libavutil_sha256",),"0"*64),
                 (("cohort_script_sha256",),"0"*64),(("source_sha256","native_dovi_adapter.c"),"0"*64),
                 (("ubsan","cases"),True),(("ubsan","diagnostics_empty"),1),
                 (("memory","swap_current_after_bytes"),1),(("memory","events_after","oom"),1),
                 (("memory","max_bytes"),True),(("case_evidence",0,"normal_exit_status"),False),
                 (("case_evidence",0,"ubsan_stdout_sha256"),"0"*64),
                 (("case_evidence",0,"normal_stderr_sha256"),"0"*64)]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"report.json"
            for keys,value in changes:
                modified=copy.deepcopy(original);target=modified
                for key in keys[:-1]: target=target[key]
                target[keys[-1]]=value;path.write_text(json.dumps(modified))
                with self.subTest(keys=keys),self.assertRaises(ValueError): load_archive(path)


if __name__=="__main__": unittest.main()
