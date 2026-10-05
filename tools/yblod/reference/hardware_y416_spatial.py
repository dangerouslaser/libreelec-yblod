"""Small isolated-channel spatial observations of diagnostic P010->Y416.

Center profiles retain unmodified raw LE16 words at full output-pixel indices.
Output unspecified siting does not select a physical coordinate model. Native
420->444 is a conversion, never a chroma byte-identity gate or fitted oracle.
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

import hardware_y416_check as checker

CASES=("neutral",)+tuple(f"{c}-{axis}-{direction}" for c in checker.transport.CHANNELS
                         for axis in ("x","y") for direction in ("ascending","descending"))
UYVA={"Cb":0,"Y":1,"Cr":2,"alpha":3}


def case_spec(case):
    if case not in CASES:raise ValueError("unknown spatialcase")
    component,axis,direction=(None,None,None) if case=="neutral" else case.split("-")
    base={c:512 for c in checker.transport.CHANNELS}
    slope=0
    if component is not None:
        extent=64 if component=="Y" else 32
        slope=8 if direction=="ascending" else -8
        base[component]=512-slope*(extent//2)
    return {"component":component,"axis":axis,"signed_slope":slope,"base_codes_at_origin":base,
            "native_component_sizes":{"Y":[64,64],"Cb":[32,32],"Cr":[32,32]},"input_size":[64,64]}


def input_planes(case):
    spec=case_spec(case)
    return {c:[[spec["base_codes_at_origin"][c]+(spec["signed_slope"]*(x if spec["axis"]=="x" else y)
                                                   if c==spec["component"] else 0)
                for x in range(64 if c=="Y" else 32)] for y in range(64 if c=="Y" else 32)]
            for c in checker.transport.CHANNELS}


def analyse(path,size):
    if type(size) is not int or size not in (64,128):raise ValueError("native64 orscaled128 required")
    states=[{"minimum":65535,"maximum":0,"counts":{},"low4":[0]*16,"low6":[0]*64,
             "digest":hashlib.sha256(),"center_row":[],"center_column":[]} for _ in range(4)]
    digest=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for y in range(size):
            data=handle.read(size*8)
            if len(data)!=size*8:raise ValueError("truncated packedY416")
            digest.update(data)
            words=array("H");words.frombytes(data)
            if sys.byteorder!="little":words.byteswap()
            for x in range(size):
                for index,state in enumerate(states):
                    word=words[x*4+index]
                    state["minimum"]=min(state["minimum"],word);state["maximum"]=max(state["maximum"],word)
                    state["counts"][word]=state["counts"].get(word,0)+1
                    state["low4"][word&15]+=1;state["low6"][word&63]+=1
                    state["digest"].update(data[x*8+index*2:x*8+index*2+2])
                    if y==size//2:state["center_row"].append(word)
                    if x==size//2:state["center_column"].append(word)
        if handle.read(1):raise ValueError("Y416trailingbytes/stridepadding")
    positions={}
    for index,state in enumerate(states):
        values=sorted(state["counts"])
        positions[str(index)]={"samples":size*size,"minimum_raw_word":state["minimum"],"maximum_raw_word":state["maximum"],
                               "unique_value_count":len(values),"raw_word_values":values if len(values)<=32 else None,
                               "most_frequent_raw_words":[{"word":v,"count":n} for v,n in
                                                          sorted(state["counts"].items(),key=lambda kv:(-kv[1],kv[0]))[:8]],
                               "low4_histogram":state["low4"],"low6_histogram":state["low6"],
                               "raw_word_sha256":state["digest"].hexdigest(),
                               "center_row_raw_words":state["center_row"],"center_column_raw_words":state["center_column"]}
    return {"size":[size,size],"bytes":size*size*8,"sha256":digest.hexdigest(),"raw_le16_word_positions":positions,
            "profile_sampling":{"center_row_y":size//2,"center_column_x":size//2},
            "UYVA_word_indices_hypothesis":UYVA,
            "alpha_raw_word_values_under_UYVA":positions["3"]["raw_word_values"],
            "interpretation":"raw profiles at full output-pixel indices; no truncation, chroma coordinate selection, gain/shift fit or conversionidentity"}


def validate_invocation(stdout,size,fmt,copy_mode=False):
    value=json.loads(stdout)
    if (not isinstance(value.get("output_size"),list) or len(value["output_size"])!=2 or
            any(type(n) is not int for n in value["output_size"]) or value["output_size"]!=[size,size]):
        raise ValueError("spatialoutputsizeinvalid")
    expected_bytes=size*size*(3 if fmt=="p010" else 8)
    if type(value.get("output_packed_bytes")) is not int or value["output_packed_bytes"]!=expected_bytes:
        raise ValueError("spatialoutputbytecontractinvalid")
    canonical=dict(value,output_size=[64,64],output_packed_bytes=64*64*(3 if fmt=="p010" else 8))
    checker.validate_invocation(json.dumps(canonical),64,64,fmt,"full" if fmt=="p010" else "reduced",
                                copy_mode,allocation_diagnostic=fmt=="y416")
    return value


def run(binary,destination,repeats=2,device="/dev/dri/renderD128"):
    root=Path(destination).resolve();root.mkdir(exist_ok=False);started=time.monotonic()
    report={"schema":"yblod.hardware-y416-spatial.v1","status":"failed","inputs":{},"results":{},"invocations":[],
            "source_sha256":checker.large.file_hash(__file__),"kernel":list(os.uname()),"device":str(device),
            "helper_sha256":{Path(m.__file__).name:checker.large.file_hash(m.__file__) for m in
                              (checker,checker.vectors,checker.transport,checker.large,checker.siting)},
            "hardware_engine_verified":False,"allocation_diagnostic_requested":True,
            "interpretation":"unadvertisedsurface allocationdiagnostic, native420->444 and2x rawobservations, NOTconversionidentity or fitted Dolby geometry"}

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
        if entry["exit_status"]!=0:raise ValueError("spatialformatprobe failed/timedout; nofallback")
        entry["invocation"]=validate_invocation(stdout,size,fmt,copy_mode)
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
                print(f"Y416spatial P010gatecomplete {'copy' if copy_mode else 'native'}/{case}",file=sys.stderr,flush=True)
        report["all_sameformat_p010_gates_complete"]=True
        for size in (64,128):
            cases=report["results"].setdefault(str(size),{})
            for case in inputs:
                paths=[call(case,size,"y416",n)[0] for n in range(repeats)];hashes=[checker.large.file_hash(p) for p in paths]
                if len(set(hashes))!=1:raise ValueError("Y416spatialrawrepeatdiffers")
                result=analyse(paths[0],size);result.update(repeat_sha256=hashes,repeat_stable=True);cases[case]=result
                print(f"Y416spatial observedcomplete {size}/{case}",file=sys.stderr,flush=True)
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF)
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                          "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","interpretation":"PythonprocesslifetimeRSS; diagnosticelapsednotplayback"}
    with (root/"y416-spatial-report.json").open("x") as handle:json.dump(report,handle,indent=2,sort_keys=True);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("binary",type=Path);parser.add_argument("destination",type=Path)
    parser.add_argument("--repeats",type=int,default=2);parser.add_argument("--device",default="/dev/dri/renderD128")
    args=parser.parse_args();result=run(args.binary,args.destination,args.repeats,args.device)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"y416-spatial-report.json"),"invocations":len(result["invocations"])}))
    raise SystemExit(result["status"]!="complete")
