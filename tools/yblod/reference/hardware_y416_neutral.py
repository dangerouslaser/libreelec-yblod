"""One-code synthetic Y416 observations near neutral; no precision policy chosen."""
import argparse
from array import array
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

import hardware_y416_large as large

CASES=("neutral","Y-x-step-plus","Cb-y-step-minus","Cr-x-stripe-plus")
MAX_RAW_BYTES=300*1024*1024


def case_spec(case,width=64,height=64):
    large.checker.large.dimensions(width,height)
    if case=="neutral":component=axis=kind=None;delta=0
    else:
        fields=case.split("-")
        if len(fields)!=4:raise ValueError("component-axis-kind-sign case required")
        component,axis,kind,sign=fields
        if component not in ("Y","Cb","Cr") or axis not in ("x","y") or kind not in ("step","stripe","stair") or sign not in ("plus","minus"):
            raise ValueError("unsupported explicit one-code case")
        delta=1 if sign=="plus" else -1
    extent=(width if axis=="x" else height)//(1 if component=="Y" else 2) if component else None
    return {"component":component,"axis":axis,"kind":kind,"signed_code_increment":delta,"baseline_code":512,
            "source_change_index":extent//2 if extent else None,"stair_native_period":8 if kind=="stair" else None,
            "native_component_sizes":{"Y":[width,height],"Cb":[width//2,height//2],"Cr":[width//2,height//2]}}


def source_code(spec,component,x,y):
    if component!=spec["component"]:return 512
    coordinate=x if spec["axis"]=="x" else y;center=spec["source_change_index"]
    active=coordinate>=center if spec["kind"]=="step" else coordinate==center
    if spec["kind"]=="stair":active=(coordinate//8)%2==1
    return 512+spec["signed_code_increment"]*active


def generate(path,case,width=64,height=64):
    spec=case_spec(case,width,height);digest=hashlib.sha256()
    with Path(path).open("xb") as handle:
        for chroma,rows in ((False,height),(True,height//2)):
            for row in range(rows):
                values=array("H",(source_code(spec,c,x,row)<<6 for x in range(width//2 if chroma else width)
                                  for c in (("Cb","Cr") if chroma else ("Y",))))
                if sys.byteorder!="little":values.byteswap()
                data=values.tobytes();handle.write(data);digest.update(data)
    return {"file":Path(path).name,"bytes":width*height*3,"sha256":digest.hexdigest(),"case_spec":spec}


def near_neutral(path,width,height):
    hist=[Counter() for _ in range(3)]
    with Path(path).open("rb") as handle:
        for _ in range(height):
            data=handle.read(width*8)
            if len(data)!=width*8:raise ValueError("truncated near-neutral surface")
            words=array("H");words.frombytes(data)
            if sys.byteorder!="little":words.byteswap()
            for index in range(3):hist[index].update(v-32768 for v in words[index::4] if 0<abs(v-32768)<=32)
        if handle.read(1):raise ValueError("extra near-neutral surface bytes")
    return {component:{"nonzero_within_half_native_code_count":sum(hist[index].values()),
                       "raw_delta_histogram":[{"delta":v,"count":hist[index][v]} for v in sorted(hist[index])],
                       "native_code_denominator":64,"interpretation":"raw-word observations only; not NLQ precision selection"}
            for index,component in enumerate(("Cb","Y","Cr"))}


def run(binary,destination,width=64,height=64,repeats=2,device="/dev/dri/renderD128",*,cases=CASES,native_y416=True):
    large.checker.large.dimensions(width,height)
    if type(repeats) is not int or repeats!=2 or type(native_y416) is not bool:raise ValueError("exactly2 repeats and explicit native boolean required")
    if type(cases) not in (tuple,list) or not 2<=len(cases)<=4 or cases[0]!="neutral" or len(set(cases))!=len(cases):raise ValueError("2..4 unique cases, neutral first required")
    for case in cases:case_spec(case,width,height)
    raw_budget=len(cases)*width*height*(9+repeats*8*(4+int(native_y416)))
    if raw_budget>MAX_RAW_BYTES:raise ValueError("cohort exceeds300MiB raw budget; reduce cases/omit nativeY416 explicitly")
    executable=Path(binary).resolve();binary_pin=large.checker.large.file_hash(executable)
    root=Path(destination).resolve();root.mkdir(exist_ok=False);started=time.monotonic()
    modules=(large,large.checker,large.checker.large,large.checker.vectors,large.checker.transport,large.checker.siting)
    report={"schema":"yblod.hardware-y416-neutral.v1","status":"failed","input_size":[width,height],"output_size":[2*width,2*height],
            "repeats":repeats,"case_count":len(cases),"native_y416_requested":native_y416,"planned_raw_bytes":raw_budget,
            "binary_sha256":binary_pin,"source_sha256":large.checker.large.file_hash(__file__),
            "helper_sha256":{Path(m.__file__).name:large.checker.large.file_hash(m.__file__) for m in modules},
            "inputs":{},"invocations":[],"results":{},"hardware_engine_verified":False,
            "interpretation":"one-code synthetic offscreen diagnostics, no fitted phase or truncation/NLQ/Dolby/display policy"}
    def call(case,scale,fmt,repeat=0,copy=False):
        stem=f"{'copy' if copy else 'default'}-{fmt}-{case}-{scale}x-{repeat}";out=root/f"{stem}.{fmt}"
        argv=[str(executable),str(device),str(root/report["inputs"][case]["file"]),str(out),str(width),str(height),str(width*scale),str(height*scale),"copy" if copy else "default"]
        if not copy:
            argv += ["--input-chroma","left","--output-chroma","left" if fmt=="p010" else "unspecified","--output-format",fmt,
                     "--range","full" if fmt=="p010" else "reduced","--pipeline","default"]
            if fmt=="y416":argv += ["--surface-contract","allocation-diagnostic"]
        entry={"argv":argv,"case":case,"format":fmt,"size":[width*scale,height*scale],"output_file":out.name};report["invocations"].append(entry)
        try:
            result=subprocess.run(argv,capture_output=True,timeout=60,check=False)
            stdout,stderr=result.stdout,result.stderr;entry["exit_status"]=result.returncode
        except subprocess.TimeoutExpired as error:
            stdout,stderr=error.stdout or b"",error.stderr or b"";entry.update(exit_status=None,timed_out=True)
        for kind,data in (("stdout",stdout),("stderr",stderr)):
            log=root/f"{stem}.{kind}.log";log.write_bytes(data);entry[kind]={"file":log.name,"sha256":hashlib.sha256(data).hexdigest()}
        if out.exists():entry["output_sha256"]=large.checker.large.file_hash(out)
        if entry["exit_status"]!=0:raise ValueError("probe failure; no fallback")
        entry["invocation"]=large.validate_invocation(stdout,width,height,width*scale,height*scale,fmt,copy)
        return out
    try:
        if shutil.disk_usage(root).free<raw_budget+64*1024*1024:raise ValueError("insufficient disk reserve")
        for case in cases:report["inputs"][case]=generate(root/f"{case}-input.p010",case,width,height)
        for copy in (True,False):
            for case in cases:
                path=call(case,1,"p010",copy=copy);identity=large.p010_identity(path,report["inputs"][case],width,height)
                report["invocations"][-1]["identity"]=identity
                if not identity["exact"]:raise ValueError("P010 identity gate failed")
        report["all_sameformat_p010_gates_complete"]=True
        for stage,scale in ((("native",1),("scaled",2)) if native_y416 else (("scaled",2),)):
            values=report["results"].setdefault(stage,{})
            for case in cases:
                print(f"near-neutral {stage}/{case}",file=sys.stderr,flush=True)
                outputs=[call(case,scale,"y416",repeat=n) for n in range(repeats)]
                pins=[large.checker.large.file_hash(p) for p in outputs]
                if len(set(pins))!=1:raise ValueError("unstable repeated Y416 words")
                value=large.analyse(outputs[0],width*scale,height*scale)
                value.update(repeat_sha256=pins,repeat_stable=True,near_neutral=near_neutral(outputs[0],width*scale,height*scale))
                if case=="neutral" and any(value["raw_le16_word_positions"][str(i)]["raw_word_values"]!=[32768] for i in range(3)):
                    raise ValueError("neutral colour preservation failed; alpha is not gated")
                values[case]=value
        if large.checker.large.file_hash(executable)!=binary_pin:raise ValueError("probe binary changed")
        for record in report["inputs"].values():
            path=root/record["file"]
            if path.stat().st_size!=record["bytes"] or large.checker.large.file_hash(path)!=record["sha256"]:
                raise ValueError("synthetic input changed after generation")
        if large.checker.large.file_hash(__file__)!=report["source_sha256"] or any(large.checker.large.file_hash(m.__file__)!=report["helper_sha256"][Path(m.__file__).name] for m in modules):
            raise ValueError("runner/helper source changed")
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","own_cgroup_memory":large.cgroup_snapshot(),"playback_measurement":False}
    with (root/"y416-neutral-report.json").open("x") as handle:json.dump(report,handle,indent=2);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("binary");parser.add_argument("destination")
    parser.add_argument("--width",type=int,default=64);parser.add_argument("--height",type=int,default=64)
    parser.add_argument("--cases",nargs="+",default=CASES);parser.add_argument("--omit-native-y416",action="store_true")
    args=parser.parse_args();value=run(args.binary,args.destination,args.width,args.height,cases=args.cases,native_y416=not args.omit_native_y416)
    print(json.dumps({"status":value["status"],"invocations":len(value["invocations"])}));raise SystemExit(value["status"]!="complete")
