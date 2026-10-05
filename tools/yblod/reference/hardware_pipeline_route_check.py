"""Per-job VA pipeline-hint diagnostics, not a portable engine guarantee.

Only default/fast pipeline flags vary. Quality stays default and chroma stays
left-to-left. No Kodi/global setting, inferred routing fix, or fallback.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import hardware_scaling_controls as controls
import hardware_chroma_siting_check as siting

# Confirmed against the actual probe build SDK: VA_PROC_PIPELINE_FAST=0x2.
ROUTES = {"default": 0, "fast": 2}
PATTERNS = controls.RAMPS+("channel-tags",)


def validate_invocation(stdout, width, height, scale, route, copy_mode=False):
    value = json.loads(stdout)
    if value.get("input_size") != [width,height] or value.get("output_size") != [width*scale,height*scale]:
        raise ValueError("pipeline invocation dimensions differ")
    if any(not isinstance(value[k],list) or any(type(n) is not int for n in value[k]) for k in ("input_size","output_size")):
        raise ValueError("pipeline invocation dimension types invalid")
    canonical = dict(value,input_size=[64,64],output_size=[64,64])
    siting.validate_invocation(json.dumps(canonical),64,"left","left",copy_mode)
    for key in ("pipeline_flags","pipeline_caps_flags"):
        if key not in value: raise ValueError(f"missing pipeline metadata: {key}")
        if copy_mode:
            if value[key] is not None: raise ValueError("copy pipeline metadata must be null")
        elif type(value[key]) is not int or value[key] < 0:
            raise ValueError("VPP pipeline metadata must be nonnegative integer")
    if not copy_mode:
        expected = ROUTES[route]
        if value["pipeline_flags"] != expected: raise ValueError("submitted pipeline hint differs")
        if expected and value["pipeline_caps_flags"] & expected != expected:
            raise ValueError("requested pipeline hint not advertised; no fallback allowed")
    return value


def run(binary,destination,width=1920,height=1080,repeats=2,device="/dev/dri/renderD128"):
    root=Path(destination).resolve()
    root.mkdir(exist_ok=False)
    started=time.monotonic()
    report={"schema":"yblod.hardware-pipeline-route-check.v1","status":"failed","inputs":{},"results":{},
            "invocations":[],"hardware_engine_verified":False,"kernel":list(os.uname()),"device":str(device),
            "source_sha256":controls.large.file_hash(__file__),
            "helper_sha256":{Path(module.__file__).name:controls.large.file_hash(module.__file__)
                              for module in (controls,controls.large,siting,controls.transport)},
            "pipeline_hints":ROUTES,
            "interpretation":"per-job advertised pipeline-hint response; no fallback, global playback change or portable hardware-engine guarantee"}

    def call(pattern,route,scale,repetition=0,copy_mode=False):
        stem=f"{'copy' if copy_mode else route}-{pattern}-{scale}x-{repetition}"
        output=root/f"{stem}.p010"
        argv=[str(executable),str(device),str(root/f"{pattern}-input.p010"),str(output),
              str(width),str(height),str(width*scale),str(height*scale),"copy" if copy_mode else "default"]
        if not copy_mode:argv += ["--input-chroma","left","--output-chroma","left","--pipeline",route]
        entry={"argv":argv,"pattern":pattern,"requested_route":None if copy_mode else route,"output_file":output.name}
        report["invocations"].append(entry)
        try:
            result=subprocess.run(argv,capture_output=True,timeout=60,check=False)
            stdout,stderr=result.stdout,result.stderr
            entry["exit_status"]=result.returncode
        except subprocess.TimeoutExpired as error:
            stdout,stderr=error.stdout or b"",error.stderr or b""
            entry.update(exit_status=None,timed_out=True)
        except OSError as error:
            stdout,stderr=b"",str(error).encode()
            entry.update(exit_status=None,spawn_error=type(error).__name__)
        for kind,data in (("stdout",stdout),("stderr",stderr)):
            path=root/f"{stem}.{kind}.log"
            with path.open("xb") as handle:handle.write(data)
            entry[kind]={"file":path.name,"sha256":hashlib.sha256(data).hexdigest()}
        if output.exists():entry["output_sha256"]=controls.large.file_hash(output)
        if entry["exit_status"] != 0:raise ValueError("pipeline probe failed or hint unsupported; no fallback")
        entry["invocation"]=validate_invocation(stdout,width,height,scale,route,copy_mode)
        return output,entry

    try:
        controls.large.dimensions(width,height)
        if type(repeats) is not int or not 2<=repeats<=4:raise ValueError("2..4 repeats required")
        executable=Path(binary).resolve()
        report.update(binary=str(executable),binary_sha256=controls.large.file_hash(executable),
                      input_size=[width,height],output_size=[width*2,height*2],repeats=repeats)
        for pattern in PATTERNS:
            report["inputs"][pattern]=controls.generate(root/f"{pattern}-input.p010",pattern,0,width,height)
        score_cache={}
        for route in ("copy",*ROUTES):
            for pattern in PATTERNS:
                path,entry=call(pattern,"default" if route=="copy" else route,1,copy_mode=route=="copy")
                digest=controls.large.file_hash(path)
                key=(pattern,1,digest)
                if key not in score_cache:score_cache[key]=controls.scan(path,pattern,0,width,height,1)
                entry["scan"]=score_cache[key]
                entry["identity_exact"]=digest==report["inputs"][pattern]["sha256"]
                if not entry["identity_exact"]:raise ValueError(f"pipeline native identity failed: {route}/{pattern}")
                print(f"route native complete {route}/{pattern}",file=sys.stderr,flush=True)
        report["all_native_route_gates_complete"]=True
        for route in ROUTES:
            cases=report["results"].setdefault(route,{})
            for pattern in PATTERNS:
                paths=[call(pattern,route,2,n)[0] for n in range(repeats)]
                hashes=[controls.large.file_hash(path) for path in paths]
                if len(set(hashes)) != 1:raise ValueError("pipeline scaled repeats differ")
                key=(pattern,2,hashes[0])
                if key not in score_cache:score_cache[key]=controls.scan(paths[0],pattern,0,width,height,2)
                result=copy.deepcopy(score_cache[key])
                result.update(repeat_sha256=hashes,repeat_stable=True)
                cases[pattern]=result
                if any(c["samples"]==0 for c in result["channels"].values()):raise ValueError("empty route scored interior")
                if pattern=="channel-tags" and not all(c["constant_codes_preserved"] for c in result["channels"].values()):
                    raise ValueError("pipeline constant/channel tags changed")
                print(f"route scaled complete {route}/{pattern}",file=sys.stderr,flush=True)
        report["route_hash_comparison"]={p:{"sha256":{r:report["results"][r][p]["sha256"] for r in ROUTES},
                                            "equal":report["results"]["default"][p]["sha256"]==report["results"]["fast"][p]["sha256"]}
                                         for p in PATTERNS}
        report["status"]="complete"
    except Exception as error:
        report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF)
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                          "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB",
                          "interpretation":"Python process lifetime peakRSS only; elapsed includes CPU scans, not playback"}
    with (root/"pipeline-route-report.json").open("x") as handle:
        json.dump(report,handle,indent=2,sort_keys=True)
        handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--width",type=int,default=1920)
    parser.add_argument("--height",type=int,default=1080)
    parser.add_argument("--repeats",type=int,default=2)
    parser.add_argument("--device",default="/dev/dri/renderD128")
    args=parser.parse_args()
    result=run(args.binary,args.destination,args.width,args.height,args.repeats,args.device)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"pipeline-route-report.json"),
                      "invocations":len(result["invocations"])}))
    raise SystemExit(result["status"]!="complete")
