"""Diagnostic isolated steps/stripe impulses; raw words, no fitted response.

Non-driven channels and alpha are observed against the same-size neutral
baseline, never presumed unchanged or opaque. P010 same-format identity gates
all conversion. Y416 conversion is explicitly unadvertised allocation testing.
"""
import argparse
from array import array
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import hardware_y416_spatial as spatial

CASES=("neutral",)+tuple(f"{c}-{axis}-{kind}" for c in spatial.checker.transport.CHANNELS
                         for axis in ("x","y") for kind in ("step","impulse"))


def case_spec(case):
    if case not in CASES:raise ValueError("unknown edgecase")
    component,axis,kind=(None,None,"neutral") if case=="neutral" else case.split("-")
    return {"component":component,"axis":axis,"kind":kind,"baseline_code":512,"increment_code":64,
            "change_native_index":None if component is None else (32 if component=="Y" else 16),
            "native_component_sizes":{"Y":[64,64],"Cb":[32,32],"Cr":[32,32]},"input_size":[64,64]}


def input_planes(case):
    spec=case_spec(case)
    result={}
    for c in spatial.checker.transport.CHANNELS:
        extent=64 if c=="Y" else 32;rows=[]
        for y in range(extent):
            row=[]
            for x in range(extent):
                coordinate=x if spec["axis"]=="x" else y
                driven=c==spec["component"] and (coordinate>=spec["change_native_index"] if spec["kind"]=="step"
                                                 else coordinate==spec["change_native_index"])
                row.append(512+64*int(driven))
            rows.append(row)
        result[c]=rows
    return result


def compare_baseline(path,baseline,size):
    """Every raw word compared; no conversion scale, signed clamp or fitting."""
    if type(size) is not int or size not in (64,128):raise ValueError("native64/scaled128required")
    states=[{"samples":0,"different":0,"minimum_signed_raw_delta":65535,"maximum_signed_raw_delta":-65535,
             "maximum_absolute_raw_delta":0,"sum_signed_raw_delta":0} for _ in range(4)]
    with Path(path).open("rb") as actual,Path(baseline).open("rb") as neutral:
        for _ in range(size):
            a,b=actual.read(size*8),neutral.read(size*8)
            if len(a)!=size*8 or len(b)!=size*8:raise ValueError("truncated baselinecomparison")
            aw,bw=array("H"),array("H");aw.frombytes(a);bw.frombytes(b)
            if sys.byteorder!="little":aw.byteswap();bw.byteswap()
            for pixel in range(size):
                for index,state in enumerate(states):
                    delta=aw[pixel*4+index]-bw[pixel*4+index]
                    state["samples"]+=1;state["different"]+=int(delta!=0)
                    state["minimum_signed_raw_delta"]=min(state["minimum_signed_raw_delta"],delta)
                    state["maximum_signed_raw_delta"]=max(state["maximum_signed_raw_delta"],delta)
                    state["maximum_absolute_raw_delta"]=max(state["maximum_absolute_raw_delta"],abs(delta))
                    state["sum_signed_raw_delta"]+=delta
        if actual.read(1) or neutral.read(1):raise ValueError("baselinecomparison trailingbytes")
    return {"baseline_case":"neutral","baseline_sha256":spatial.checker.large.file_hash(baseline),
            "actual_sha256":spatial.checker.large.file_hash(path),"raw_word_positions":{str(i):s for i,s in enumerate(states)},
            "interpretation":"whole-frame raw differences; non-driven channels and alpha observed, NOTforcedconstant or opaque"}


def run(binary,destination,repeats=2,device="/dev/dri/renderD128"):
    root=Path(destination).resolve();root.mkdir(exist_ok=False);started=time.monotonic()
    checker=spatial.checker
    report={"schema":"yblod.hardware-y416-edges.v1","status":"failed","inputs":{},"results":{},"invocations":[],
            "source_sha256":checker.large.file_hash(__file__),"kernel":list(os.uname()),"device":str(device),
            "helper_sha256":{Path(m.__file__).name:checker.large.file_hash(m.__file__) for m in
                              (spatial,checker,checker.vectors,checker.transport,checker.large,checker.siting)},
            "hardware_engine_verified":False,"allocation_diagnostic_requested":True,
            "interpretation":"safe isolated step/stripe rawresponse diagnostics, no area/plateau normalization, fit or certifiedDVgeometry"}

    def call(case,size,fmt,repetition=0,copy_mode=False):
        stem=f"{'copy' if copy_mode else 'default'}-{fmt}-{case}-{size}-{repetition}";output=root/f"{stem}.{fmt}"
        argv=[str(executable),str(device),str(root/f"{case}-input.p010"),str(output),"64","64",str(size),str(size),
              "copy" if copy_mode else "default"]
        if not copy_mode:
            argv += ["--input-chroma","left","--output-chroma","left" if fmt=="p010" else "unspecified",
                     "--output-format",fmt,"--range","full" if fmt=="p010" else "reduced","--pipeline","default"]
            if fmt=="y416":argv += ["--surface-contract","allocation-diagnostic"]
        entry={"argv":argv,"case":case,"output_file":output.name,"format":fmt,"size":[size,size]}
        report["invocations"].append(entry)
        try:
            result=subprocess.run(argv,capture_output=True,timeout=30,check=False)
            stdout,stderr=result.stdout,result.stderr;entry["exit_status"]=result.returncode
        except subprocess.TimeoutExpired as error:
            stdout,stderr=error.stdout or b"",error.stderr or b"";entry.update(exit_status=None,timed_out=True)
        except OSError as error:
            stdout,stderr=b"",str(error).encode();entry.update(exit_status=None,spawn_error=type(error).__name__)
        for kind,data in (("stdout",stdout),("stderr",stderr)):
            path=root/f"{stem}.{kind}.log"
            with path.open("xb") as handle:handle.write(data)
            entry[kind]={"file":path.name,"sha256":hashlib.sha256(data).hexdigest()}
        if output.exists():entry["output_sha256"]=checker.large.file_hash(output)
        if entry["exit_status"]!=0:raise ValueError("edgeformatprobe failed/timedout; nofallback")
        entry["invocation"]=spatial.validate_invocation(stdout,size,fmt,copy_mode)
        return output,entry

    try:
        if type(repeats) is not int or not 2<=repeats<=4:raise ValueError("2..4repeatsrequired")
        executable=Path(binary).resolve();report.update(binary=str(executable),binary_sha256=checker.large.file_hash(executable),repeats=repeats)
        inputs={case:input_planes(case) for case in CASES}
        for case,planes in inputs.items():
            data=checker.transport.pack_p010(planes)
            with (root/f"{case}-input.p010").open("xb") as handle:handle.write(data)
            report["inputs"][case]={"file":f"{case}-input.p010","sha256":hashlib.sha256(data).hexdigest(),"case_spec":case_spec(case)}
        for copy_mode in (True,False):
            for case,planes in inputs.items():
                path,entry=call(case,64,"p010",copy_mode=copy_mode)
                entry["identity"]=checker.vectors.check_identity(planes,path.read_bytes())
                if not entry["identity"]["exact"]:raise ValueError("P010sameformatidentityfailed")
                print(f"Y416edges P010gatecomplete {'copy' if copy_mode else 'native'}/{case}",file=sys.stderr,flush=True)
        report["all_sameformat_p010_gates_complete"]=True
        for size in (64,128):
            cases=report["results"].setdefault(str(size),{});baseline=None
            for case in inputs:
                paths=[call(case,size,"y416",n)[0] for n in range(repeats)];hashes=[checker.large.file_hash(p) for p in paths]
                if len(set(hashes))!=1:raise ValueError("Y416edgerawrepeatdiffers")
                result=spatial.analyse(paths[0],size);result.update(repeat_sha256=hashes,repeat_stable=True)
                if baseline is None:baseline=paths[0]
                result["differences_from_neutral"]=compare_baseline(paths[0],baseline,size);cases[case]=result
                print(f"Y416edges observedcomplete {size}/{case}",file=sys.stderr,flush=True)
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF)
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                          "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","interpretation":"PythonprocesslifetimeRSS; diagnosticelapsednotplayback"}
    with (root/"y416-edges-report.json").open("x") as handle:json.dump(report,handle,indent=2,sort_keys=True);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("binary",type=Path);parser.add_argument("destination",type=Path)
    parser.add_argument("--repeats",type=int,default=2);parser.add_argument("--device",default="/dev/dri/renderD128")
    args=parser.parse_args();result=run(args.binary,args.destination,args.repeats,args.device)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"y416-edges-report.json"),"invocations":len(result["invocations"])}))
    raise SystemExit(result["status"]!="complete")
