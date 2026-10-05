"""Diagnostic alternatives for observed near-neutral words; no selected policy."""
import argparse
import ctypes as C
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from nlq_stage import NLQConfig, correction


class NativeConfig(C.Structure):
    _fields_=[("bit_depth",C.c_int32),("denominator",C.c_int32),("offset",C.c_int32),
              ("slope",C.c_uint64),("threshold",C.c_uint64),("maximum",C.c_uint64)]


class Rational(C.Structure):
    _fields_=[("uncapped_numerator",C.c_int64),("capped_numerator",C.c_int64),
              ("divisor",C.c_uint64),("floored_residual",C.c_int64)]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(data):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("duplicate JSON key")
            result[key]=value
        return result
    def nonfinite(value):raise ValueError("nonfinite JSON number")
    return json.loads(data,object_pairs_hook=pairs,parse_constant=nonfinite)


def observations(report):
    if report.get("schema")!="yblod.hardware-y416-neutral.v1" or report.get("status")!="complete" or report.get("all_sameformat_p010_gates_complete") is not True:
        raise ValueError("completed near-neutral report required")
    rows=[]
    for stage,cases in report["results"].items():
        for case,result in cases.items():
            if result.get("repeat_stable") is not True or len(set(result["repeat_sha256"]))!=1:
                raise ValueError("stable repeated words required")
            for component,channel in result["near_neutral"].items():
                hist=channel["raw_delta_histogram"]
                if component not in ("Y","Cb","Cr") or type(channel["native_code_denominator"]) is not int or channel["native_code_denominator"]!=64:
                    raise ValueError("declared colour Q6 observations required")
                seen=set();total=0
                for entry in hist:
                    delta,count=entry["delta"],entry["count"]
                    if type(delta) is not int or not 0<abs(delta)<=32 or delta in seen or type(count) is not int or count<=0:
                        raise ValueError("invalid signed raw histogram")
                    seen.add(delta);total+=count
                    rows.append({"stage":stage,"case":case,"component":component,"raw_word":32768+delta,"count":count})
                if type(channel["nonzero_within_half_native_code_count"]) is not int or total!=channel["nonzero_within_half_native_code_count"]:
                    raise ValueError("histogram count mismatch")
    return rows


def analyse(report_path):
    report_path=Path(report_path)
    if not report_path.is_file() or report_path.stat().st_size>8*1024*1024:raise ValueError("bounded regular report required")
    before=digest(report_path)
    report=strict_json(report_path.read_text());rows=observations(report)
    here=Path(__file__).resolve().parent
    sources=[here/name for name in ("native_composer.c","native_composer.h","native_precision_probe.c","native_precision_probe.h","nlq_stage.py",Path(__file__).name)]
    pins={p.name:digest(p) for p in sources}
    words=sorted({32768}|{row["raw_word"] for row in rows});answers=[]
    cfg=NativeConfig(10,23,512,2048,0,1048576)
    independent=NLQConfig(10,23,512,2048,0,1048576)
    with tempfile.TemporaryDirectory() as scratch:
        library=Path(scratch)/"precision.so"
        argv=["cc","-std=c11","-O2","-fPIC","-shared","-Wall","-Wextra","-Werror","-Wconversion","-Wshadow",
              str(here/"native_composer.c"),str(here/"native_precision_probe.c"),"-o",str(library)]
        subprocess.run(argv,check=True,capture_output=True,timeout=30)
        binary_sha=digest(library);lib=C.CDLL(str(library))
        lib.yb_probe_quantized.argtypes=[C.POINTER(NativeConfig),C.c_int64,C.c_int32,C.POINTER(C.c_int32),C.POINTER(C.c_int64)]
        lib.yb_probe_literal.argtypes=[C.POINTER(NativeConfig),C.c_int64,C.POINTER(Rational)]
        for word in words:
            entry={"raw_word":word,"policies":{}}
            floor,remainder=divmod(word,64)
            expected=(floor,floor+(remainder>=32),floor+(remainder>32 or remainder==32 and floor%2==1))
            for policy,name in enumerate(("floor","nearest_half_up","nearest_ties_even")):
                sample,residual=C.c_int32(),C.c_int64()
                if lib.yb_probe_quantized(C.byref(cfg),word,policy,C.byref(sample),C.byref(residual))!=0:raise ValueError("native quantized failure")
                if (sample.value,residual.value)!=(expected[policy],correction(expected[policy],independent)):raise ValueError("integer independent mismatch")
                entry["policies"][name]={"native_code":sample.value,"integer_residual":residual.value}
            value=Rational()
            if lib.yb_probe_literal(C.byref(cfg),word,C.byref(value))!=0:raise ValueError("native literal failure")
            exact=Fraction(value.capped_numerator,value.divisor)
            delta=Fraction(word,64)-512;sign=(delta>0)-(delta<0)
            if exact!=16*delta-8*sign or value.floored_residual!=exact.numerator//exact.denominator:raise ValueError("exact diagnostic mismatch")
            entry["hypothetical_literal"]={"numerator":exact.numerator,"denominator":exact.denominator,"floored_residual":value.floored_residual,
                                          "opposite_sign_to_raw_delta":bool(delta and exact and (delta>0)!=(exact>0))}
            answers.append(entry)
    if digest(report_path)!=before or any(digest(p)!=pins[p.name] for p in sources):raise ValueError("source/report changed")
    return {"schema":"yblod.hardware-y416-neutral-precision.v1","status":"complete","observation_report_sha256":before,
            "source_sha256":pins,"native_library_sha256":binary_sha,"observations":rows,"alternatives":answers,
            "fixture":{"bit_depth":10,"denominator":23,"offset":512,"slope":2048,"threshold":0,"maximum":1048576},
            "interpretation":"Artificial arithmetic fixture, not movie metadata or licensed behaviour. Literal extension is hypothetical, without shader noise guard. No policy selected; no production change."}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("report");parser.add_argument("new_output")
    args=parser.parse_args();result=analyse(args.report)
    with Path(args.new_output).open("x") as handle:json.dump(result,handle,indent=2);handle.write("\n")
