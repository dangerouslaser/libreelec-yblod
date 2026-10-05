"""Bounded synthetic GPU diagnostic runner; not a playback benchmark."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import time

from hardware_y416_neutral_precision import strict_json
from native_gpu_probe import encode
from native_gpu_vectors import expected_stages, vector_fixtures, width_oracle

SOURCES = ("native_gpu_probe.c", "native_gpu_probe.comp", "native_gpu_probe.py",
           "native_gpu_probe_fixture.c", "native_gpu_probe_fixture.h",
           "native_composer.c", "native_composer.h", "native_gpu_guard.c",
           "native_gpu_guard.h", "native_gpu_vectors.py", "native_stage.py",
           "base_mapping_stage.py", "nlq_stage.py", "composition_stage.py",
           "hardware_y416_neutral_precision.py", "native_gpu_run.py")


def digest(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
    with os.fdopen(descriptor,"rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 32*1024*1024:
            raise ValueError("bounded regular diagnostic file required")
        value = hashlib.sha256()
        total=0
        while block := stream.read(65536):
            total+=len(block)
            if total>32*1024*1024:raise ValueError("file grew beyond diagnostic bound")
            value.update(block)
        after = os.fstat(stream.fileno())
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("file changed during hashing")
    return value.hexdigest()


def validate_cpu(report, vector):
    expected = expected_stages(vector)
    rows = [list(row) for row in zip(*expected)]
    width = width_oracle(vector.mapping)
    polynomial = all(segment.method == "polynomial"
                     for curve in vector.mapping.mappings for segment in curve.segments)
    accepted = polynomial and width["supported"]
    expected_width = dict(supported=width["supported"], mmr_segment_count=width["mmr_segment_count"],
        worst_l1_bound=width["worst_l1_bound"], first_unsupported_component=width["first_unsupported"][0],
        first_unsupported_segment=width["first_unsupported"][1])
    required=dict(schema="yblod.native-gpu-probe.v1",gpu_attempted=False,accepted=accepted,
        polynomial_only=polynomial,width_report=expected_width,samples=len(vector.triplets),
        component=vector.component,cpu_stages=rows,status="validated" if accepted else "unsupported")
    if type(report) is not dict or any(not same_typed(report.get(k),v) for k,v in required.items()):
        raise ValueError("native CPU validation differs from independent oracle")
    return accepted


def validate_gpu(report, vector):
    width=width_oracle(vector.mapping)
    required=dict(schema="yblod.native-gpu-probe.v1",status="exact",gpu_attempted=True,accepted=True,
        polynomial_only=True,device_binding_verified=True,cleanup_succeeded=True,
        observed_gl_error=0,observed_egl_error=12288,stage_mismatch_counts=[0]*4,
        samples=len(vector.triplets),component=vector.component,
        width_report=dict(supported=width["supported"],mmr_segment_count=width["mmr_segment_count"],
            worst_l1_bound=width["worst_l1_bound"],first_unsupported_component=width["first_unsupported"][0],
            first_unsupported_segment=width["first_unsupported"][1]))
    if type(report) is not dict or any(not same_typed(report.get(k),v) for k,v in required.items()):
        raise ValueError("GPU stages, device association or cleanup failed")
    if type(report.get("fence_wait_result")) is not int or report["fence_wait_result"] not in (37146,37148):
        raise ValueError("GPU completion fence did not succeed")


def same_typed(actual, expected):
    if type(actual) is not type(expected):return False
    if type(expected) is dict:
        return actual.keys()==expected.keys() and all(same_typed(actual[k],v) for k,v in expected.items())
    if type(expected) is list:
        return len(actual)==len(expected) and all(same_typed(a,b) for a,b in zip(actual,expected))
    return actual==expected


def cgroup_snapshot():
    try:
        entry=next(row.split(":",2)[2] for row in Path("/proc/self/cgroup").read_text().splitlines() if row.startswith("0::"))
        root=Path("/sys/fs/cgroup")/entry.lstrip("/")
        result={}
        for name in ("memory.current","memory.peak","memory.max","memory.swap.current","memory.swap.max",
                     "memory.events","memory.stat","memory.pressure"):
            path=root/name
            if path.exists():result[name]=path.read_text().strip()
        return dict(status="observed",values=result)
    except (OSError,StopIteration):return dict(status="unavailable")


def run(binary, shader, destination, device="/dev/dri/renderD128"):
    if not re.fullmatch(r"/dev/dri/renderD[0-9]+", device) or not 128 <= int(device.split("renderD")[1]) <= 1048575:
        raise ValueError("explicit render node required")
    binary = Path(binary).resolve(strict=True)
    shader = Path(shader).resolve(strict=True)
    if not os.access(binary, os.X_OK):raise ValueError("executable diagnostic required")
    here = Path(__file__).resolve().parent
    source_pins = {name:digest(here/name) for name in SOURCES}
    binary_pin, shader_pin = digest(binary), digest(shader)
    if shader_pin != source_pins["native_gpu_probe.comp"]:
        raise ValueError("the reviewed diagnostic shader is required")
    vectors = vector_fixtures()
    if not 1 <= len(vectors) <= 32 or sum(len(v.triplets) for v in vectors) > 65536:
        raise ValueError("fixture cohort exceeds bounded diagnostic limits")
    if len({v.name for v in vectors}) != len(vectors) or any(not re.fullmatch(r"[A-Za-z0-9_-]+",v.name) for v in vectors):
        raise ValueError("unique safe fixture names required")
    fixtures = [(v, encode(v.mapping,v.nlq,v.component,v.triplets,v.el_samples,v.output_depth)) for v in vectors]
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    started = time.monotonic()
    report = dict(schema="yblod.native-gpu-run.v1", status="failed", source_sha256=source_pins,
        binary_sha256=binary_pin, shader_sha256=shader_pin, requested_render_node=device,
        fixture_count=len(vectors), cases=[], interpretation="Synthetic whole-code correctness diagnostic; not playback, fractional EL policy, colour conversion or HDMI validation.")
    report["cgroup_before"]=cgroup_snapshot()

    def pins_unchanged():
        if digest(binary) != binary_pin or digest(shader) != shader_pin or any(digest(here/n)!=p for n,p in source_pins.items()):
            raise ValueError("diagnostic binary, shader or sources changed")

    def invoke(case, argv, phase):
        pins_unchanged()
        path = root/(case["name"]+".bin")
        if digest(path) != case["fixture_sha256"]:raise ValueError("fixture changed")
        invocation = dict(argv=argv)
        case[phase] = invocation
        try:
            result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
            stdout, stderr = result.stdout, result.stderr
            invocation["exit_status"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            invocation.update(exit_status=None, timed_out=True)
        for kind, data in (("stdout",stdout),("stderr",stderr)):
            log = root/(case["name"]+"-"+phase+"."+kind+".log")
            with log.open("xb") as stream:stream.write(data)
            invocation[kind] = dict(file=log.name,sha256=hashlib.sha256(data).hexdigest())
        pins_unchanged()
        if digest(path) != case["fixture_sha256"]:raise ValueError("fixture changed during invocation")
        if invocation["exit_status"] is None or len(stdout)>4*1024*1024:
            raise ValueError("diagnostic timed out or report exceeded bound")
        invocation["report"] = strict_json(stdout)
        return invocation

    try:
        for vector, data in fixtures:
            path = root/(vector.name+".bin")
            with path.open("xb") as stream:stream.write(data)
            report["cases"].append(dict(name=vector.name, fixture_sha256=digest(path), fixture_bytes=len(data)))
        accepted = []
        # Every independent CPU gate completes before any GPU context is opened.
        for (vector,_), case in zip(fixtures, report["cases"]):
            result = invoke(case,[str(binary),"--validate",str(root/(vector.name+".bin"))],"validation")
            eligible = validate_cpu(result["report"],vector)
            if result["exit_status"] != (0 if eligible else 3):raise ValueError("unexpected validator exit")
            case["gpu_eligible"] = eligible
            if eligible:accepted.append((vector,case))
        report["all_cpu_gates_complete"] = True
        if not accepted:raise ValueError("no eligible GPU fixtures; execution not demonstrated")
        for vector,case in accepted:
            result = invoke(case,[str(binary),device,str(shader),str(root/(vector.name+".bin"))],"gpu")
            if result["exit_status"] != 0:raise ValueError("native GPU diagnostic failed")
            validate_gpu(result["report"],vector)
        pins_unchanged()
        report.update(status="complete",gpu_case_count=len(accepted),unsupported_case_count=len(vectors)-len(accepted))
    except Exception as error:
        report["error"] = dict(type=type(error).__name__,message=str(error))
    report["elapsed_seconds"] = time.monotonic()-started
    report["resources"]=dict(self_peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        child_peak_rss_native=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        rss_native_unit="bytes" if sys.platform=="darwin" else "KiB",cgroup_after=cgroup_snapshot(),
        playback_measurement=False)
    with (root/"gpu-run-report.json").open("x") as stream:
        json.dump(report,stream,indent=2);stream.write("\n")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary");parser.add_argument("shader");parser.add_argument("destination")
    parser.add_argument("--device",default="/dev/dri/renderD128")
    args=parser.parse_args()
    result=run(args.binary,args.shader,args.destination,args.device)
    print(json.dumps({"status":result["status"],"cases":len(result["cases"])}))
    raise SystemExit(result["status"]!="complete")
