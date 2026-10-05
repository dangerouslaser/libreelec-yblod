"""Row-bounded full-size isolated affine-band Y416 observations.

No full-frame Python integer planes, bit truncation, chosen chroma geometry or
fitted correction. Counter aggregation preserves every raw16 word while using
one row at a time. Whole-channel comparisons to neutral remain observations.
"""
import argparse
from array import array
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import hardware_y416_check as checker

CASES=("neutral",)+tuple(f"{c}-{axis}-ascending" for c in checker.transport.CHANNELS for axis in ("x","y"))
MARGIN=32


def case_spec(case,width=1920,height=1080):
    checker.large.dimensions(width,height)
    if case not in CASES:raise ValueError("unknown largeY416case")
    component,axis=(None,None) if case=="neutral" else case.split("-")[:2]
    extent=(width if axis=="x" else height)//(1 if component=="Y" else 2) if component else None
    length=min(96,extent) if extent else None;start=(extent-length)//2 if extent else None
    return {"component":component,"axis":axis,"signed_slope":8 if component else 0,"baseline_code":512,
            "native_band_length":length,"band_start_native":start,
            "band_stop_native_exclusive":start+length if component else None,
            "source_center_native_index":start+length//2 if component else None,
            "band_first_code":512-8*(length//2) if component else None,
            "band_last_code":512+8*(length-1-length//2) if component else None,
            "native_component_sizes":{"Y":[width,height],"Cb":[width//2,height//2],"Cr":[width//2,height//2]},
            "input_size":[width,height]}


def source_code(spec,component,x,y):
    if component!=spec["component"]:return 512
    m=x if spec["axis"]=="x" else y
    k=max(0,min(spec["native_band_length"]-1,m-spec["band_start_native"]))
    return spec["band_first_code"]+8*k


def generate(path,case,width=1920,height=1080):
    spec=case_spec(case,width,height);vertical=spec["axis"]=="y"
    cached_y=None if vertical and spec["component"]=="Y" else checker.large._bytes(array("H",(source_code(spec,"Y",x,0)<<6 for x in range(width))))
    cached_uv=None if vertical and spec["component"] in ("Cb","Cr") else checker.large._bytes(array("H",(source_code(spec,c,x,0)<<6
                                                                                                          for x in range(width//2) for c in ("Cb","Cr"))))
    digest=hashlib.sha256()
    with Path(path).open("xb") as handle:
        for chroma,count in ((False,height),(True,height//2)):
            for y in range(count):
                if chroma:data=cached_uv if cached_uv is not None else b"".join((source_code(spec,c,0,y)<<6).to_bytes(2,"little") for c in ("Cb","Cr"))*(width//2)
                else:data=cached_y if cached_y is not None else (source_code(spec,"Y",0,y)<<6).to_bytes(2,"little")*width
                handle.write(data);digest.update(data)
    return {"file":Path(path).name,"bytes":width*height*3,"sha256":digest.hexdigest(),"case_spec":spec}


def p010_identity(path,record,width,height):
    """Stream every P010 word; identity is exact original packed bytes."""
    digest=hashlib.sha256();words_count=0
    with Path(path).open("rb") as handle:
        for _ in range(height+height//2):
            data=handle.read(width*2)
            if len(data)!=width*2:raise ValueError("truncatedP010nativeframe")
            digest.update(data);words=array("H");words.frombytes(data)
            if sys.byteorder!="little":words.byteswap()
            if any(v&63 for v in words):raise ValueError("P010unusedlowbitsnonzero")
            words_count+=len(words)
        if handle.read(1):raise ValueError("P010trailingbytes/stridepadding")
    return {"exact":digest.hexdigest()==record["sha256"],"sha256":digest.hexdigest(),"full_code_samples":words_count,
            "unused_low_bits_zero":True,"interpretation":"row-streamed native-code transport identity, notconversionidentity"}


def analyse(path,width,height):
    if type(width) is not int or type(height) is not int or width<=0 or height<=0 or width>3840 or height>2160:
        raise ValueError("boundedpositiveY416dimensionsrequired")
    states=[{"counts":Counter(),"low4":[0]*16,"low6":[0]*64,"digest":hashlib.sha256(),"center_row":[],"center_column":[]} for _ in range(4)]
    digest=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for y in range(height):
            data=handle.read(width*8)
            if len(data)!=width*8:raise ValueError("truncatedlargepackedY416")
            digest.update(data);words=array("H");words.frombytes(data)
            if sys.byteorder!="little":words.byteswap()
            for index,state in enumerate(states):
                values=words[index::4];counts=Counter(values);state["counts"].update(counts)
                for v,n in counts.items():state["low4"][v&15]+=n;state["low6"][v&63]+=n
                raw=values.tobytes()
                if sys.byteorder!="little":encoded=array("H",values);encoded.byteswap();raw=encoded.tobytes()
                state["digest"].update(raw)
                if y==height//2:state["center_row"]=list(values)
                state["center_column"].append(values[width//2])
        if handle.read(1):raise ValueError("Y416trailingbytes/stridepadding")
    positions={}
    for index,state in enumerate(states):
        values=sorted(state["counts"])
        positions[str(index)]={"samples":width*height,"minimum_raw_word":values[0],"maximum_raw_word":values[-1],
                               "unique_value_count":len(values),"raw_word_values":values if len(values)<=32 else None,
                               "most_frequent_raw_words":[{"word":v,"count":n} for v,n in sorted(state["counts"].items(),key=lambda kv:(-kv[1],kv[0]))[:8]],
                               "low4_histogram":state["low4"],"low6_histogram":state["low6"],"raw_word_sha256":state["digest"].hexdigest(),
                               "center_row_raw_words":state["center_row"],"center_column_raw_words":state["center_column"]}
    return {"size":[width,height],"bytes":width*height*8,"sha256":digest.hexdigest(),"raw_le16_word_positions":positions,
            "profile_sampling":{"center_row_y":height//2,"center_column_x":width//2},"UYVA_word_indices_hypothesis":{"Cb":0,"Y":1,"Cr":2,"alpha":3},
            "alpha_raw_word_values_under_UYVA":positions["3"]["raw_word_values"],
            "interpretation":"every rawword counted, centerprofiles in fulloutputpixel indices; no assumedbitdepth or fittedgeometry"}


def validate_invocation(stdout,width,height,out_width,out_height,fmt,copy_mode=False):
    value=json.loads(stdout)
    for key,expected in (("input_size",[width,height]),("output_size",[out_width,out_height])):
        if not isinstance(value.get(key),list) or value[key]!=expected or len(value[key])!=2 or any(type(v) is not int for v in value[key]):
            raise ValueError("largeY416invocationdimensionsinvalid")
    expected_bytes=out_width*out_height*(3 if fmt=="p010" else 8)
    if type(value.get("output_packed_bytes")) is not int or value["output_packed_bytes"]!=expected_bytes:raise ValueError("largeY416packedbytesinvalid")
    canonical=dict(value,input_size=[64,64],output_size=[64,64],output_packed_bytes=64*64*(3 if fmt=="p010" else 8))
    checker.validate_invocation(json.dumps(canonical),64,64,fmt,"full" if fmt=="p010" else "reduced",copy_mode,allocation_diagnostic=fmt=="y416")
    return value


def profile_window(spec,width,height,scale):
    if spec["component"] is None:return None
    native_extent=spec["native_component_sizes"][spec["component"]][0 if spec["axis"]=="x" else 1]
    output_extent=(width if spec["axis"]=="x" else height)*scale;ratio=output_extent//native_extent
    start=spec["band_start_native"]*ratio+MARGIN;stop=spec["band_stop_native_exclusive"]*ratio-MARGIN
    if stop<=start:raise ValueError("emptyconservativebandprofilewindow")
    return {"axis":spec["axis"],"start_output_index":start,"stop_output_index_exclusive":stop,
            "margin_output_samples":MARGIN,"interpretation":"conservative logicalbandinterior only, not selectedphysicalregistration"}


def cgroup_snapshot():
    """Optional read-only snapshot of this process's unified memory scope."""
    try:
        line=next(v for v in Path("/proc/self/cgroup").read_text().splitlines() if v.startswith("0::"))
        relative=line.split("::",1)[1]
        root=Path("/sys/fs/cgroup").resolve();scope=(root/relative.lstrip("/")).resolve()
        if scope!=root and root not in scope.parents:raise ValueError("cgroupscopeoutsideunifiedroot")
        result={"available":True,"scope":str(scope)}
        for name in ("memory.current","memory.peak","memory.swap.current","memory.events"):
            try:
                text=(scope/name).read_text().strip()
                result[name]={k:int(v) for k,v in (line.split() for line in text.splitlines())} if name=="memory.events" else int(text)
            except (OSError,ValueError):result[name]=None
        return result
    except (OSError,ValueError,StopIteration):return {"available":False}


def run(binary,destination,width=1920,height=1080,repeats=2,device="/dev/dri/renderD128",*,neutral_only=False):
    root=Path(destination).resolve();root.mkdir(exist_ok=False);started=time.monotonic()
    report={"schema":"yblod.hardware-y416-large.v1","status":"failed","inputs":{},"results":{},"invocations":[],
            "source_sha256":checker.large.file_hash(__file__),"kernel":list(os.uname()),"device":str(device),"output_band_margin_samples":MARGIN,
            "helper_sha256":{Path(m.__file__).name:checker.large.file_hash(m.__file__) for m in (checker,checker.vectors,checker.transport,checker.large,checker.siting)},
            "hardware_engine_verified":False,"allocation_diagnostic_requested":True,
            "interpretation":"fullsizeisolatedsafe-band rawdiagnostics, notadvertisedsurfacecontract, fit orDVcertification"}

    def call(case,scale,fmt,repetition=0,copy_mode=False):
        stem=f"{'copy' if copy_mode else 'default'}-{fmt}-{case}-{scale}x-{repetition}";output=root/f"{stem}.{fmt}"
        argv=[str(executable),str(device),str(root/f"{case}-input.p010"),str(output),str(width),str(height),str(width*scale),str(height*scale),"copy" if copy_mode else "default"]
        if not copy_mode:
            argv += ["--input-chroma","left","--output-chroma","left" if fmt=="p010" else "unspecified","--output-format",fmt,
                     "--range","full" if fmt=="p010" else "reduced","--pipeline","default"]
            if fmt=="y416":argv += ["--surface-contract","allocation-diagnostic"]
        entry={"argv":argv,"case":case,"output_file":output.name,"format":fmt,"size":[width*scale,height*scale]};report["invocations"].append(entry)
        try:
            result=subprocess.run(argv,capture_output=True,timeout=60,check=False);stdout,stderr=result.stdout,result.stderr;entry["exit_status"]=result.returncode
        except subprocess.TimeoutExpired as error:stdout,stderr=error.stdout or b"",error.stderr or b"";entry.update(exit_status=None,timed_out=True)
        except OSError as error:stdout,stderr=b"",str(error).encode();entry.update(exit_status=None,spawn_error=type(error).__name__)
        for kind,data in (("stdout",stdout),("stderr",stderr)):
            path=root/f"{stem}.{kind}.log"
            with path.open("xb") as handle:handle.write(data)
            entry[kind]={"file":path.name,"sha256":hashlib.sha256(data).hexdigest()}
        if output.exists():entry["output_sha256"]=checker.large.file_hash(output)
        if entry["exit_status"]!=0:raise ValueError("largeformatprobe failed/timedout; nofallback")
        entry["invocation"]=validate_invocation(stdout,width,height,width*scale,height*scale,fmt,copy_mode);return output,entry

    try:
        checker.large.dimensions(width,height)
        if type(neutral_only) is not bool:raise ValueError("neutralonlymustbeexplicitboolean")
        active_cases=("neutral",) if neutral_only else CASES
        report.update(corpus="neutral-only" if neutral_only else "isolated-ascending",case_count=len(active_cases))
        if type(repeats) is not int or not 2<=repeats<=4:raise ValueError("2..4repeatsrequired")
        # Full-size default uses96-sample bands; smaller fixtures remain useful
        # only if the fixed32-output-sample margin still leaves an interior.
        for case in active_cases:
            spec=case_spec(case,width,height)
            if case!="neutral":
                profile_window(spec,width,height,1);profile_window(spec,width,height,2)
        executable=Path(binary).resolve();report.update(binary=str(executable),binary_sha256=checker.large.file_hash(executable),input_size=[width,height],output_size=[width*2,height*2],repeats=repeats)
        for case in active_cases:report["inputs"][case]=generate(root/f"{case}-input.p010",case,width,height)
        for copy_mode in (True,False):
            for case in active_cases:
                path,entry=call(case,1,"p010",copy_mode=copy_mode);entry["identity"]=p010_identity(path,report["inputs"][case],width,height)
                if not entry["identity"]["exact"]:raise ValueError("largeP010sameformatidentityfailed")
                print(f"largeY416 P010gatecomplete {'copy' if copy_mode else 'native'}/{case}",file=sys.stderr,flush=True)
        report["all_sameformat_p010_gates_complete"]=True
        for stage,scale in (("native",1),("scaled",2)):
            cases=report["results"].setdefault(stage,{});neutral=None
            for case in active_cases:
                paths=[call(case,scale,"y416",n)[0] for n in range(repeats)];hashes=[checker.large.file_hash(p) for p in paths]
                if len(set(hashes))!=1:raise ValueError("largeY416rawrepeatdiffers")
                print(f"largeY416 scanning {stage}/{case}",file=sys.stderr,flush=True)
                value=analyse(paths[0],width*scale,height*scale);value.update(repeat_sha256=hashes,repeat_stable=True)
                value["diagnostic_band_profile_window"]=profile_window(report["inputs"][case]["case_spec"],width,height,scale)
                if neutral is None:neutral=value
                value["whole_raw_word_hash_comparison_to_neutral"]={i:{"equal":v["raw_word_sha256"]==neutral["raw_le16_word_positions"][i]["raw_word_sha256"],
                                                                       "neutral_raw_word_values":neutral["raw_le16_word_positions"][i]["raw_word_values"]}
                                                                     for i,v in value["raw_le16_word_positions"].items()}
                cases[case]=value;print(f"largeY416 observedcomplete {stage}/{case}",file=sys.stderr,flush=True)
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF);report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                                                                   "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","interpretation":"PythonprocesslifetimeRSS; diagnosticelapsednotplayback"}
    report["resources"]["own_cgroup_memory"]=cgroup_snapshot()
    with (root/"y416-large-report.json").open("x") as handle:json.dump(report,handle,indent=2,sort_keys=True);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("binary",type=Path);parser.add_argument("destination",type=Path)
    parser.add_argument("--width",type=int,default=1920);parser.add_argument("--height",type=int,default=1080)
    parser.add_argument("--repeats",type=int,default=2);parser.add_argument("--device",default="/dev/dri/renderD128")
    parser.add_argument("--neutral-only",action="store_true",help="explicit six-job full-size safety checkpoint before isolated ramps")
    args=parser.parse_args();result=run(args.binary,args.destination,args.width,args.height,args.repeats,args.device,neutral_only=args.neutral_only)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"y416-large-report.json"),"invocations":len(result["invocations"])}));raise SystemExit(result["status"]!="complete")
