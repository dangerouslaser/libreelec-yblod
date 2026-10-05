"""Separate full-size descending, step and integer-placement stripe checkpoints.

All raw files retained. Stripe 'phase0/1' suffixes mean integer SOURCE sample
placements, NOT a new fractional resampler phase. Source-safe descending
96-sample bands mirror128..888, so ascent+descent equals1016, not1024.
"""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import os

import hardware_y416_large as large

CORPORA={"descending":("neutral",)+tuple(f"{c}-{a}-descending" for c in large.checker.transport.CHANNELS for a in ("x","y")),
         "edges":("neutral",)+tuple(f"{c}-{a}-step" for c in large.checker.transport.CHANNELS for a in ("x","y")),
         "stripes":("neutral",)+tuple(f"{c}-{a}-stripe-phase{p}" for c in large.checker.transport.CHANNELS for a in ("x","y") for p in (0,1))}


def case_spec(case,width=1920,height=1080):
    large.checker.large.dimensions(width,height)
    if not any(case in cases for cases in CORPORA.values()):raise ValueError("unknownlargedetailcase")
    parts=case.split("-");component=None if case=="neutral" else parts[0];axis=None if component is None else parts[1]
    kind="neutral" if component is None else parts[2];offset=int(parts[3][-1]) if kind=="stripe" else None
    extent=(width if axis=="x" else height)//(1 if component=="Y" else 2) if component else None
    length=min(96,extent) if kind=="descending" else None;start=(extent-length)//2 if length else None
    spec={"component":component,"axis":axis,"kind":kind,"phase":offset,"source_index_offset":offset,
          "baseline_code":512,"signed_slope":-8 if kind=="descending" else 0,"increment_code":64 if kind in ("step","stripe") else 0,
          "change_native_index":extent//2+(offset or 0) if kind in ("step","stripe") else None,
          "native_band_length":length,"band_start_native":start,"band_stop_native_exclusive":start+length if length else None,
          "source_center_native_index":extent//2 if component else None,
          "band_first_code":512+8*(length-1-length//2) if length else None,"band_last_code":512-8*(length//2) if length else None,
          "source_center_code":504 if kind=="descending" else (512 if component else None),
          "native_component_sizes":{"Y":[width,height],"Cb":[width//2,height//2],"Cr":[width//2,height//2]},"input_size":[width,height]}
    if kind=="stripe":
        spec["placement_interpretation"]="integer native component sample placement, not a fractional resampler phase"
        spec["integer_output_translation_hypothesis"]={"native":offset*(1 if component=="Y" else 2),"scaled":offset*(2 if component=="Y" else 4)}
    return spec


def source_code(spec,component,x,y):
    if component!=spec["component"]:return 512
    m=x if spec["axis"]=="x" else y
    if spec["kind"]=="descending":return spec["band_first_code"]-8*max(0,min(spec["native_band_length"]-1,m-spec["band_start_native"]))
    if spec["kind"]=="step":return 512+64*int(m>=spec["change_native_index"])
    if spec["kind"]=="stripe":return 512+64*int(m==spec["change_native_index"])
    raise ValueError("unknowndrivensourcekind")


def generate(path,case,width=1920,height=1080):
    spec=case_spec(case,width,height);vertical=spec["axis"]=="y";helper=large.checker.large
    cached_y=None if vertical and spec["component"]=="Y" else helper._bytes(array("H",(source_code(spec,"Y",x,0)<<6 for x in range(width))))
    cached_uv=None if vertical and spec["component"] in ("Cb","Cr") else helper._bytes(array("H",(source_code(spec,c,x,0)<<6 for x in range(width//2) for c in ("Cb","Cr"))))
    digest=hashlib.sha256()
    with Path(path).open("xb") as handle:
        for chroma,count in ((False,height),(True,height//2)):
            for y in range(count):
                if chroma:data=cached_uv if cached_uv is not None else b"".join((source_code(spec,c,0,y)<<6).to_bytes(2,"little") for c in ("Cb","Cr"))*(width//2)
                else:data=cached_y if cached_y is not None else (source_code(spec,"Y",0,y)<<6).to_bytes(2,"little")*width
                handle.write(data);digest.update(data)
    return {"file":Path(path).name,"bytes":width*height*3,"sha256":digest.hexdigest(),"case_spec":spec}


def profile_window(spec,width,height,scale):
    if spec["kind"]=="descending":return large.profile_window(spec,width,height,scale)
    return None  # Step/stripe response must not be hidden by an affine-band mask.


def run(binary,destination,corpus="descending",width=1920,height=1080,repeats=2,device="/dev/dri/renderD128"):
    root=Path(destination).resolve();root.mkdir(exist_ok=False);started=time.monotonic();checker=large.checker
    report={"schema":"yblod.hardware-y416-large-detail.v1","status":"failed","inputs":{},"results":{},"invocations":[],"corpus":corpus,
            "source_sha256":checker.large.file_hash(__file__),"kernel":list(os.uname()),"device":str(device),"output_band_margin_samples":large.MARGIN,
            "helper_sha256":{Path(m.__file__).name:checker.large.file_hash(m.__file__) for m in (large,checker,checker.vectors,checker.transport,checker.large,checker.siting)},
            "hardware_engine_verified":False,"allocation_diagnostic_requested":True,
            "interpretation":"separate rawfullsize checkpoints; stripephase labels are integer source placements, no fractionalphase inference, fittedgain, normalization or deletion"}

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
        if entry["exit_status"]!=0:raise ValueError("detailformatprobe failed/timedout; nofallback")
        entry["invocation"]=large.validate_invocation(stdout,width,height,width*scale,height*scale,fmt,copy_mode);return output,entry

    try:
        checker.large.dimensions(width,height)
        if corpus not in CORPORA:raise ValueError("explicitcorpus descending/edges/stripesrequired")
        if type(repeats) is not int or not 2<=repeats<=4:raise ValueError("2..4repeatsrequired")
        cases_to_run=CORPORA[corpus];report["case_count"]=len(cases_to_run)
        # Conservative reserve includes inputs, both native gates, ALL repeats
        # of native/scaledY416. No raw file is removed, even after hash equality.
        estimated=len(cases_to_run)*width*height*(9+40*repeats);free=shutil.disk_usage(root).free
        report["disk_space_at_start"]={"free_bytes":free,"estimated_retained_frame_bytes":estimated,"minimum_extra_reserve_bytes":256<<20}
        if free<estimated+(256<<20):raise ValueError("insufficientdiskforretainedrawcheckpoint")
        for case in cases_to_run:
            spec=case_spec(case,width,height)
            if spec["kind"]=="descending":profile_window(spec,width,height,1);profile_window(spec,width,height,2)
        executable=Path(binary).resolve();report.update(binary=str(executable),binary_sha256=checker.large.file_hash(executable),input_size=[width,height],output_size=[width*2,height*2],repeats=repeats)
        for case in cases_to_run:report["inputs"][case]=generate(root/f"{case}-input.p010",case,width,height)
        for copy_mode in (True,False):
            for case in cases_to_run:
                path,entry=call(case,1,"p010",copy_mode=copy_mode);entry["identity"]=large.p010_identity(path,report["inputs"][case],width,height)
                if not entry["identity"]["exact"]:raise ValueError("detailP010sameformatidentityfailed")
                print(f"largeY416detail P010gatecomplete {'copy' if copy_mode else 'native'}/{case}",file=sys.stderr,flush=True)
        report["all_sameformat_p010_gates_complete"]=True
        for stage,scale in (("native",1),("scaled",2)):
            cases=report["results"].setdefault(stage,{});neutral=None
            for case in cases_to_run:
                paths=[call(case,scale,"y416",n)[0] for n in range(repeats)];hashes=[checker.large.file_hash(p) for p in paths]
                if len(set(hashes))!=1:raise ValueError("detailY416rawrepeatdiffers")
                print(f"largeY416detail scanning {stage}/{case}",file=sys.stderr,flush=True)
                value=large.analyse(paths[0],width*scale,height*scale);value.update(repeat_sha256=hashes,repeat_stable=True)
                value["diagnostic_band_profile_window"]=profile_window(report["inputs"][case]["case_spec"],width,height,scale)
                if neutral is None:neutral=value
                value["whole_raw_word_hash_comparison_to_neutral"]={i:{"equal":v["raw_word_sha256"]==neutral["raw_le16_word_positions"][i]["raw_word_sha256"],
                                                                       "neutral_raw_word_values":neutral["raw_le16_word_positions"][i]["raw_word_values"]}
                                                                     for i,v in value["raw_le16_word_positions"].items()}
                cases[case]=value;print(f"largeY416detail observedcomplete {stage}/{case}",file=sys.stderr,flush=True)
        report["status"]="complete"
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    usage=resource.getrusage(resource.RUSAGE_SELF);report["resources"]={"elapsed_seconds":time.monotonic()-started,"self_peak_rss_native":usage.ru_maxrss,
                                                                   "rss_native_unit":"bytes" if sys.platform=="darwin" else "KiB","interpretation":"PythonprocesslifetimeRSS; diagnosticelapsednotplayback",
                                                                   "own_cgroup_memory":large.cgroup_snapshot()}
    with (root/"y416-large-detail-report.json").open("x") as handle:json.dump(report,handle,indent=2,sort_keys=True);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("binary",type=Path);parser.add_argument("destination",type=Path)
    parser.add_argument("--corpus",choices=tuple(CORPORA),default="descending");parser.add_argument("--width",type=int,default=1920);parser.add_argument("--height",type=int,default=1080)
    parser.add_argument("--repeats",type=int,default=2);parser.add_argument("--device",default="/dev/dri/renderD128")
    args=parser.parse_args();result=run(args.binary,args.destination,args.corpus,args.width,args.height,args.repeats,args.device)
    print(json.dumps({"status":result["status"],"report":str(args.destination/"y416-large-detail-report.json"),"invocations":len(result["invocations"])}));raise SystemExit(result["status"]!="complete")
