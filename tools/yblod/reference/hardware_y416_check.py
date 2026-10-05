"""Constant-only packed-Y416 observation; never assume lower bits are zero.

Raw LE16 word indices are authoritative. U,Y,V,A and A,V,Y,U interpretations
are reported as hypotheses until distinct tags resolve the order. Conversion
420->444 is NOT byte identity; only unchanged P010 transport is an identity
gate. Full/reduced flags at both ends do not prescribe an endpoint clamp here.
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

import hardware_scaling_vectors as vectors
import scaling_probe as transport
import hardware_scaling_large as large
import hardware_chroma_siting_check as siting

FOURCC = {"p010": 0x30313050, "y416": 0x36313459}
RT_FORMAT = {"p010": 0x100, "y416": 0x4000}  # Confirmed actual probe SDK macros.
CODES = (0,1,63,64,65,512,939,940,941,1022,1023)
CASES = tuple(f"code-{c}" for c in CODES)+("channel-tags",)
RANGES = {"full":2,"reduced":1}
MAPPINGS = {"UYVA":{"Cb":0,"Y":1,"Cr":2,"alpha":3},
            "AVYU":{"alpha":0,"Cr":1,"Y":2,"Cb":3}}


def native_codes(case):
    if case=="channel-tags":return {"Y":512,"Cb":384,"Cr":640}
    if case not in CASES:raise ValueError("unknown constant probe")
    code=int(case.split("-")[1])
    return {c:code for c in transport.CHANNELS}


def input_planes(case,width=64,height=64):
    if type(width) is not int or type(height) is not int or width not in (64,128) or height not in (64,128):
        raise ValueError("initial native conversion probes require64/128 even dimensions")
    codes=native_codes(case)
    return {c:[[codes[c]]*(width if c=="Y" else width//2)
               for _ in range(height if c=="Y" else height//2)] for c in transport.CHANNELS}


def analyse(path,codes,width=64,height=64):
    """Every raw word counted without bit clearing, normalizing, or fitting."""
    input_planes("channel-tags",width,height)  # validates bounded probe geometry
    if set(codes)!=set(transport.CHANNELS) or any(type(v) is not int or not 0<=v<=1023 for v in codes.values()):
        raise ValueError("declared native codes required")
    states=[{"minimum":65535,"maximum":0,"counts":{},"low4":[0]*16,"low6":[0]*64,
             "digest":hashlib.sha256()} for _ in range(4)]
    digest=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for _ in range(height):
            data=handle.read(width*8)
            if len(data)!=width*8:raise ValueError("truncated tightly packed Y416")
            digest.update(data)
            words=array("H");words.frombytes(data)
            if sys.byteorder!="little":words.byteswap()
            for pixel in range(width):
                for index,state in enumerate(states):
                    word=words[pixel*4+index]
                    state["minimum"]=min(state["minimum"],word)
                    state["maximum"]=max(state["maximum"],word)
                    state["counts"][word]=state["counts"].get(word,0)+1
                    state["low4"][word&15]+=1
                    state["low6"][word&63]+=1
                    state["digest"].update(data[pixel*8+index*2:pixel*8+index*2+2])
        if handle.read(1):raise ValueError("Y416 trailingbytes/stridepadding")
    positions={}
    for index,state in enumerate(states):
        values=sorted(state["counts"])
        positions[str(index)]={"samples":width*height,"minimum_raw_word":state["minimum"],
                               "maximum_raw_word":state["maximum"],"unique_value_count":len(values),
                               "raw_word_values":values if len(values)<=32 else None,
                               "most_frequent_raw_words":[{"word":v,"count":n} for v,n in
                                                          sorted(state["counts"].items(),key=lambda kv:(-kv[1],kv[0]))[:8]],
                               "spatially_uniform":len(values)==1,"low4_histogram":state["low4"],
                               "low6_histogram":state["low6"],"raw_word_sha256":state["digest"].hexdigest()}
    hypotheses={}
    for name,mapping in MAPPINGS.items():
        scales={}
        for factor in (1,4,16,64):
            channels={c:{"expected_raw_word":codes[c]*factor,
                         "matching_samples":states[mapping[c]]["counts"].get(codes[c]*factor,0)} for c in transport.CHANNELS}
            scales[str(factor)]={"channels":channels,"all_color_words_match":all(v["matching_samples"]==width*height for v in channels.values())}
        alpha=positions[str(mapping["alpha"])]
        hypotheses[name]={"word_indices":mapping,"native_code_scale_hypotheses":scales,
                          "alpha_raw_word_values":alpha["raw_word_values"],
                          "alpha_all_65535":alpha["minimum_raw_word"]==alpha["maximum_raw_word"]==65535}
    return {"sha256":digest.hexdigest(),"bytes":width*height*8,"size":[width,height],
            "raw_le16_word_positions":positions,"mapping_hypotheses":hypotheses,
            "interpretation":"raw observations and declared hypotheses only; no assumed12bitalignment, nominalrangeclamp or conversionidentity"}


def validate_invocation(stdout,width,height,output_format,range_name,copy_mode=False,allocation_diagnostic=False):
    value=json.loads(stdout)
    required={"schema":"yblod.vaapi-scaler-invocation.v1","status":"complete",
              "input_size":[width,height],"output_size":[width,height],"filter_flags":0,
              "input_fourcc":FOURCC["p010"],"output_fourcc":FOURCC[output_format],
              "input_rt_format":RT_FORMAT["p010"],"output_rt_format":RT_FORMAT[output_format],
              "output_packed_bytes":width*height*(3 if output_format=="p010" else 8),
              "input_chroma_siting":None if copy_mode else 6,
              "output_chroma_siting":None if copy_mode else (6 if output_format=="p010" else 0),
              "colour_standard":None if copy_mode else 12,"colour_range":None if copy_mode else RANGES[range_name],
              "surface_contract":"allocation-diagnostic" if allocation_diagnostic and not copy_mode else "advertised",
              "pipeline_flags":None if copy_mode else 0,"vpp_submitted":not copy_mode,"hardware_engine_verified":False}
    if RT_FORMAT[output_format] is None:raise ValueError("outputRTformat must beconfirmed from actual probe SDK")
    for key,expected in required.items():
        if key not in value or value[key]!=expected or type(value[key]) is not type(expected):
            raise ValueError(f"Y416 invocation contract differs: {key}")
    if any(len(value[key])!=2 or any(type(n) is not int for n in value[key])
           for key in ("input_size","output_size")):
        raise ValueError("Y416 invocation dimension elements must be strict integers")
    if "output_surface_advertised" not in value:raise ValueError("missing outputsurfaceadvertisement declaration")
    advertised=value["output_surface_advertised"]
    if copy_mode:
        if advertised is not None:raise ValueError("copy outputadvertisement mustbenull")
    elif type(advertised) is not bool:
        raise ValueError("VPP outputadvertisement mustbe strictboolean")
    elif not allocation_diagnostic and not advertised:
        raise ValueError("unadvertised outputsurface requires explicit allocationdiagnostic; nofallback")
    caps=value.get("pipeline_caps_flags")
    if copy_mode:
        if "pipeline_caps_flags" not in value or caps is not None:raise ValueError("copycapsmustbenull")
    elif type(caps) is not int or caps<0:raise ValueError("VPPcapsintegerrequired")
    if not isinstance(value.get("vendor"),str) or not value["vendor"].strip():raise ValueError("missingVAvendor")
    version=value.get("va_version")
    if not isinstance(version,list) or len(version)!=2 or any(type(v) is not int or v<0 for v in version):raise ValueError("missingVAversion")
    return value


def run(binary,destination,width=64,height=64,repeats=2,device="/dev/dri/renderD128",*,allocation_diagnostic=False):
    root=Path(destination).resolve();root.mkdir(exist_ok=False)
    started=time.monotonic()
    report={"schema":"yblod.hardware-y416-constant-check.v1","status":"failed","invocations":[],"inputs":{},"results":{},
            "hardware_engine_verified":False,"kernel":list(os.uname()),"device":str(device),
            "source_sha256":large.file_hash(__file__),
            "helper_sha256":{Path(m.__file__).name:large.file_hash(m.__file__) for m in (vectors,transport,large,siting)},
            "format_fourcc":FOURCC,"format_rt":RT_FORMAT,
            "allocation_diagnostic_requested":allocation_diagnostic,
            "interpretation":"same-sizeP010420->Y416444 conversion observations, NOTbyteidentity; no rawbitmasking, codefit or prescribedrangeclamp"}

    def call(case,fmt,range_name,repetition=0,copy_mode=False):
        stem=f"{'copy' if copy_mode else 'default'}-{fmt}-{range_name}-{case}-{repetition}"
        output=root/f"{stem}.{'p010' if fmt=='p010' else 'y416'}"
        argv=[str(executable),str(device),str(root/f"{case}-input.p010"),str(output),str(width),str(height),str(width),str(height),
              "copy" if copy_mode else "default"]
        if not copy_mode:
            argv += ["--input-chroma","left","--output-chroma","left" if fmt=="p010" else "unspecified",
                     "--output-format",fmt,"--range",range_name,"--pipeline","default"]
            if allocation_diagnostic:argv += ["--surface-contract","allocation-diagnostic"]
        entry={"argv":argv,"case":case,"output_file":output.name,"format":fmt,"range":range_name}
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
        if output.exists():entry["output_sha256"]=large.file_hash(output)
        if entry["exit_status"]!=0:raise ValueError("formatprobe failed/timedout; nofallback")
        entry["invocation"]=validate_invocation(stdout,width,height,fmt,range_name,copy_mode,allocation_diagnostic)
        return output,entry

    try:
        if type(allocation_diagnostic) is not bool:raise ValueError("allocationdiagnostic mustbe explicitboolean")
        if type(repeats) is not int or not 2<=repeats<=4:raise ValueError("2..4repeatsrequired")
        inputs={case:input_planes(case,width,height) for case in CASES}
        executable=Path(binary).resolve()
        report.update(binary=str(executable),binary_sha256=large.file_hash(executable),size=[width,height],repeats=repeats)
        for case,planes in inputs.items():
            data=transport.pack_p010(planes)
            with (root/f"{case}-input.p010").open("xb") as handle:handle.write(data)
            report["inputs"][case]={"file":f"{case}-input.p010","sha256":hashlib.sha256(data).hexdigest(),"native_codes":native_codes(case)}
        for copy_mode in (True,False):
            for case,planes in inputs.items():
                path,entry=call(case,"p010","full",copy_mode=copy_mode)
                entry["identity"]=vectors.check_identity(planes,path.read_bytes())
                if not entry["identity"]["exact"]:raise ValueError("sameformatP010FULLidentityfailed")
                print(f"y416 P010 gate complete {'copy' if copy_mode else 'native'}/{case}",file=sys.stderr,flush=True)
        report["all_sameformat_p010_gates_complete"]=True
        for range_name in RANGES:
            cases=report["results"].setdefault(range_name,{})
            for case in inputs:
                paths=[call(case,"y416",range_name,n)[0] for n in range(repeats)]
                hashes=[large.file_hash(p) for p in paths]
                if len(set(hashes))!=1:raise ValueError("Y416repeatedrawwordsdiffer")
                result=analyse(paths[0],native_codes(case),width,height)
                result.update(repeat_sha256=hashes,repeat_stable=True)
                cases[case]=result
                print(f"y416 observed complete {range_name}/{case}",file=sys.stderr,flush=True)
        report["range_hash_comparison"]={case:{"equal":report["results"]["full"][case]["sha256"]==report["results"]["reduced"][case]["sha256"]}
                                         for case in inputs}
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF)
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                          "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","interpretation":"PythonprocesslifetimeRSS; testelapsednotplayback"}
    with (root/"y416-report.json").open("x") as handle:json.dump(report,handle,indent=2,sort_keys=True);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary",type=Path);parser.add_argument("destination",type=Path)
    parser.add_argument("--width",type=int,default=64);parser.add_argument("--height",type=int,default=64)
    parser.add_argument("--repeats",type=int,default=2);parser.add_argument("--device",default="/dev/dri/renderD128")
    parser.add_argument("--allocation-diagnostic",action="store_true",
                        help="explicitly request allocator-accepted surfaces even if unadvertised; never a fallback")
    args=parser.parse_args();result=run(args.binary,args.destination,args.width,args.height,args.repeats,args.device,
                                      allocation_diagnostic=args.allocation_diagnostic)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"y416-report.json"),"invocations":len(result["invocations"])}))
    raise SystemExit(result["status"]!="complete")
