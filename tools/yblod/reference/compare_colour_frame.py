#!/usr/bin/env python3
"""Bounded explicit old/new colour-report comparison, never fitted tuning.

Reports provide declarations, not source authenticity. All compared pixel files
are rehashed. Optional SK4 comparison verifies its saved counter association,
two metadata CRCs and transport matrices; driver PTS is not frame proof.
"""
import argparse
from array import array
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


def _sha(value):
    if type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("strict SHA256 required")
    return value


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError("duplicate JSON field")
        result[key]=value
    return result


def _pinned_json(path):
    path=Path(path)
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    with os.fdopen(descriptor,"rb") as handle:
        initial=os.fstat(handle.fileno())
        if not stat.S_ISREG(initial.st_mode) or initial.st_size>8<<20:
            raise ValueError("JSON must be regular file no larger than8MiB")
        raw=handle.read((8<<20)+1)
    if len(raw)>8<<20: raise ValueError("report exceeds8MiB")
    pin=hashlib.sha256(raw).hexdigest()
    def invalid(value):raise ValueError("nonfinite JSON number")
    value=json.loads(raw,object_pairs_hook=_unique,parse_constant=invalid)
    if sha(path)!=pin:raise ValueError("JSON changed during load")
    return value,pin


def _identity(value):
    if type(value) is not dict or set(value)!={"frame_id","pts","time_base"}:
        raise ValueError("strict frame identity required")
    if type(value["frame_id"]) is not str or not value["frame_id"] or type(value["pts"]) is not int:
        raise ValueError("invalid frame identity")
    tb=value["time_base"]
    if type(tb) is not list or len(tb)!=2 or any(type(v) is not int or v<=0 for v in tb):
        raise ValueError("strict integer timebase required")


def _stage(root,report,name,size,width,height,new):
    record=report["stages"][name] if new else report["stages"][name.split(".")[0]]
    filename=record["file"]
    if type(filename) is not str or Path(filename).is_absolute(): raise ValueError("relative stage path required")
    path=(root/filename).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size!=size:
        raise ValueError("stage path/size mismatch")
    if new:
        if type(record.get("bytes")) is not int or record["bytes"]!=size: raise ValueError("declared stage byte count mismatch")
    elif record.get("shape")!=[height,width,3] or any(type(v) is not int for v in record["shape"]):
        raise ValueError("old stage shape mismatch")
    if sha(path)!=_sha(record["sha256"]): raise ValueError("stage SHA mismatch")
    return path


def load_pair(new_output,old_output):
    newroot,oldroot=Path(new_output).resolve(),Path(old_output).resolve()
    new,newpin=_pinned_json(newroot/"output.json")
    old,oldpin=_pinned_json(oldroot/"output.json")
    if new.get("schema")!="yblod.colour-frame-result.v1" or old.get("schema")!="yblod.output-reference.v1":
        raise ValueError("explicit new/old report schemas required")
    if new.get("status")!="complete" or old.get("status")!="complete": raise ValueError("complete reports required")
    width,height=new["width"],new["height"]
    if any(type(v) is not int or not 2<=v<=8192 for v in (width,height)) or width%2 or height%2:
        raise ValueError("bounded even dimensions required")
    if type(old["width"]) is not int or type(old["height"]) is not int or (old["width"],old["height"])!=(width,height):
        raise ValueError("old dimensions differ")
    _identity(new["identity"]);_identity(old["identity"])
    if new["identity"]!=old["identity"]: raise ValueError("frame identity differs")
    cfg=new["configuration"]
    if cfg.get("schema")!="yblod.colour-frame-config.v1" or cfg.get("source_association")!="verified-extracted-rpu":
        raise ValueError("verified extracted-source configuration required")
    if cfg.get("source_identity")!=new["identity"]: raise ValueError("configuration identity differs")
    provenance=new["source_provenance"]
    if provenance!=cfg.get("source_provenance") or provenance.get("rpu_json_sha256")!=_sha(old["rpu_sha256"]):
        raise ValueError("source RPU declaration differs")
    if cfg["source_dm"]!=old["source_dm"]: raise ValueError("source DM differs")
    if old["policy"]!="direct" or cfg["pq_policy"]!="extend-positive-negative-to-zero" or type(cfg["code_scale"]) is not int or cfg["code_scale"]!=4096:
        raise ValueError("matching direct diagnostic policy required")
    if cfg.get("chroma_expansion")!="bilinear-left-diagnostic" or old["chroma_expansion"]!="bilinear-left-edge-replicated-float64":
        raise ValueError("chroma diagnostic policies differ")
    for field in ("target_ycc","target_lms","target_offset"):
        if json.dumps(cfg[field],allow_nan=False)!=json.dumps(old[field],allow_nan=False):
            raise ValueError("target coordinate declarations differ")
    rectangle=cfg["active_rectangle"]
    if type(rectangle) is not list or len(rectangle)!=4 or any(type(v) is not int for v in rectangle): raise ValueError("strict active rectangle required")
    l,t,r,b=rectangle
    if not 0<=l<r<=width or not 0<=t<b<=height or l%2 or r%2 or rectangle!=old["active_rectangle"]:
        raise ValueError("active rectangles differ/invalid")
    if cfg.get("outside_codes")!=[0,2048,2048] or any(type(v) is not int for v in cfg["outside_codes"]):
        raise ValueError("matching historical outside-area codes required")
    paths={};pixel_pins={}
    for label,root,report,isnew in (("new",newroot,new,True),("old",oldroot,old,False)):
        paths[label]={name:_stage(root,report,name,width*height*mult,width,height,isnew)
                      for name,mult in (("transport_ipt444.u16le",6),("unembedded_tunnel.rgb8",3))}
        pixel_pins[label]={name:sha(path) for name,path in paths[label].items()}
    if sha(newroot/"output.json")!=newpin or sha(oldroot/"output.json")!=oldpin:
        raise ValueError("JSON changed during pair validation")
    return {"width":width,"height":height,"rectangle":rectangle,"identity":new["identity"],
            "new_report_sha256":newpin,"old_report_sha256":oldpin,
            "paths":paths,"pixel_pins":pixel_pins,"configuration":cfg}


def _words(data):
    words=array("H");words.frombytes(data)
    if sys.byteorder!="little":words.byteswap()
    if any(v>4095 for v in words): raise ValueError("transport codes outside12bit domain")
    return words


def _decode(data,ce=False):
    if ce:
        if len(data)%8: raise ValueError("capture rows must contain whole64bit words")
        data=b"".join(data[i:i+8][::-1] for i in range(0,len(data),8))
    for i in range(0,len(data),3):
        a,b,c=data[i:i+3]
        yield ((a<<4)|(b&15),(c<<4)|(b>>4)) if ce else ((b<<4)|(c&15),(a<<4)|(c>>4))


def _capture(path,identity_file,contract):
    path=Path(path)
    width,height=contract["width"],contract["height"]
    if width*3%8 or path.stat().st_size!=width*height*3: raise ValueError("capture size/layout mismatch")
    identity,identity_pin=_pinned_json(identity_file)
    expected=contract["identity"]
    if (type(identity.get("visible_frame_number")) is not int or type(identity.get("pts_us")) is not int
            or expected["frame_id"]!=f"{identity['source_sha256']}:{identity['visible_frame_number']}"
            or expected["pts"]*expected["time_base"][0]*1000000!=identity["pts_us"]*expected["time_base"][1]):
        raise ValueError("saved counter/source association differs")
    # Existing audited tunnel parser verifies two CRCs and coordinate matrices.
    import compare_output as parser
    rows=max(4,(6144+width-1)//width)
    if rows>height: raise ValueError("capture too short for metadata")
    with path.open("rb") as handle: raw=handle.read(rows*width*3)
    initial=parser.decode_ce(parser.np.frombuffer(raw,dtype="u1").reshape(rows,width,3))
    packets=[parser.packet(*initial,i) for i in range(2)]
    if [p[0]>>6 for p in packets]!=[1,3] or any(parser.crc32_mpeg2(p) for p in packets):
        raise ValueError("two valid capture metadata packets required")
    cfg=contract["configuration"]
    for actual,field in zip(parser.matrices(*initial),("target_ycc","target_offset","target_lms")):
        if not parser.np.array_equal(actual,cfg[field]): raise ValueError("capture coordinates differ")
    l,t,_,_=contract["rectangle"]
    if t*width+l<6144: raise ValueError("active area overlaps capture metadata")
    if sha(identity_file)!=identity_pin:raise ValueError("capture identity changed during validation")
    return {"sha256":sha(path),"identity_file_sha256":identity_pin,
            "metadata_first_copy_crc":[True,True],"transport_matrices_equal":True,
            "identity_basis":"supplied visible counter/source association; not driver PTS proof",
            "parser_source_sha256":sha(parser.__file__),
            "parser_helper_sha256":{name+".py":sha(sys.modules[name].__file__)
                                    for name in ("dvtunnel","dvlms","extract_frame","output_frame")},
            "numpy_version":parser.np.__version__}


def _summary(hist):
    n=sum(hist.values());absolute=sum(abs(v)*c for v,c in hist.items());squares=sum(v*v*c for v,c in hist.items())
    return {"samples":n,"changed_samples":n-hist[0],"signed_error_histogram":[{"error":v,"count":hist[v]} for v in sorted(hist)],
            "signed_sum":sum(v*c for v,c in hist.items()),"absolute_sum":absolute,"square_sum":squares,
            "maximum_absolute_codes":max(map(abs,hist),default=0),"mean_absolute_codes":absolute/n if n else None,
            "rmse_codes":math.sqrt(squares/n) if n else None}


def compare(new_output,old_output,*,capture=None,capture_identity=None):
    contract=load_pair(new_output,old_output)
    if (capture is None)!=(capture_identity is None): raise ValueError("capture and saved identity required together")
    capture_info=_capture(capture,capture_identity,contract) if capture is not None else None
    width,height=contract["width"],contract["height"]
    l,t,r,b=contract["rectangle"]
    hist={"raw_new_minus_old":{c:Counter() for c in ("I","P","T")},
          "packed_new_minus_old":{c:Counter() for c in ("I","P","T")}}
    if capture_info:
        hist.update({f"packed_{label}_minus_sk4":{c:Counter() for c in ("I","P","T")} for label in ("new","old")})
    packed_changed=0
    with ExitStack() as resources:
        files={label:{name:resources.enter_context(path.open("rb")) for name,path in paths.items()} for label,paths in contract["paths"].items()}
        ce=resources.enter_context(Path(capture).open("rb")) if capture_info else None
        for y in range(height):
            raw={label:_words(streams["transport_ipt444.u16le"].read(width*6)) for label,streams in files.items()}
            packed={label:streams["unembedded_tunnel.rgb8"].read(width*3) for label,streams in files.items()}
            if any(len(v)!=width*3 for v in raw.values()) or any(len(v)!=width*3 for v in packed.values()): raise ValueError("stage truncated during scan")
            packed_changed+=sum(a!=b for a,b in zip(packed["new"],packed["old"]))
            decoded={label:list(_decode(data)) for label,data in packed.items()}
            for label in ("new","old"):
                for x,(intensity,chroma) in enumerate(decoded[label]):
                    if intensity!=raw[label][3*x] or chroma!=raw[label][3*(x-x%2)+(1 if x%2==0 else 2)]:
                        raise ValueError("packed/raw code contract differs")
            theirs=list(_decode(ce.read(width*3),True)) if ce else None
            if theirs is not None and len(theirs)!=width: raise ValueError("capture truncated during scan")
            if not t<=y<b: continue
            for x in range(l,r):
                for component,index in (("I",0),("P",1),("T",2)):
                    hist["raw_new_minus_old"][component][raw["new"][3*x+index]-raw["old"][3*x+index]]+=1
                for component,index in (("I",0),("P" if x%2==0 else "T",1)):
                    hist["packed_new_minus_old"][component][decoded["new"][x][index]-decoded["old"][x][index]]+=1
                    if theirs:
                        for label in ("new","old"):
                            hist[f"packed_{label}_minus_sk4"][component][decoded[label][x][index]-theirs[x][index]]+=1
        for streams in files.values():
            if any(handle.read(1) for handle in streams.values()):raise ValueError("extra output bytes")
        if ce and ce.read(1):raise ValueError("extra capture bytes")
    # Catch replacement/changes after hashes were checked and streams consumed.
    for label,paths in contract["paths"].items():
        for name,path in paths.items():
            if sha(path)!=contract["pixel_pins"][label][name]: raise ValueError("stage changed during comparison")
    if sha(Path(new_output)/"output.json")!=contract["new_report_sha256"] or sha(Path(old_output)/"output.json")!=contract["old_report_sha256"]:
        raise ValueError("report changed during comparison")
    if capture_info and sha(capture)!=capture_info["sha256"]:raise ValueError("capture changed during comparison")
    if capture_info and sha(capture_identity)!=capture_info["identity_file_sha256"]:raise ValueError("capture identity changed during comparison")
    return {"schema":"yblod.colour-frame-comparison.v1","status":"complete",
            "scope":"raw diagnostic transport differences; not displayed colour accuracy or Dolby compliance; no fitted coordinates",
            "width":width,"height":height,"active_rectangle":contract["rectangle"],
            "new_report_sha256":contract["new_report_sha256"],"old_report_sha256":contract["old_report_sha256"],
            "compared_stage_sha256":contract["pixel_pins"],
            "implementation_sha256":sha(__file__),"packed_all_frame_changed_bytes":packed_changed,
            "packed_all_frame_byte_exact":packed_changed==0,"capture":capture_info,
            "comparisons":{label:{c:_summary(h) for c,h in channels.items()} for label,channels in hist.items()}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("new_output");parser.add_argument("old_output");parser.add_argument("new_json")
    parser.add_argument("--capture");parser.add_argument("--capture-identity")
    args=parser.parse_args()
    result=compare(args.new_output,args.old_output,capture=args.capture,capture_identity=args.capture_identity)
    with Path(args.new_json).open("x") as handle:json.dump(result,handle,indent=2,allow_nan=False);handle.write("\n")


if __name__=="__main__":main()
