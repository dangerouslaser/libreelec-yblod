#!/usr/bin/env python3
"""Synthetic direct-C chunk throughput; not full-frame or playback timing."""
import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import struct
import subprocess
import sys

import base_mapping_stage as mapping
import composition_stage as composition
import native_stage as adapter
import nlq_stage as nlq

ROOT = Path(__file__).resolve().parent
CASES = ("polynomial", "mmr1", "mmr2", "mmr3", "disabled")


class Measurement(C.Structure):
    _fields_ = [("wall_seconds", C.c_double), ("cpu_seconds", C.c_double),
                ("processed_samples", C.c_uint64), ("checksum", C.c_uint64)]


def source_hashes():
    return {name: adapter.digest(ROOT/name) for name in (
        "native_kernel_bench.c", "native_kernel_bench.py", "native_composer.c",
        "native_composer.h", "native_stage.py", "base_mapping_stage.py",
        "nlq_stage.py", "composition_stage.py")}


def fixture(case, count):
    if case not in CASES:
        raise ValueError("unknown synthetic case")
    adapter._integer(count, "count", 1, 65536)
    denominator = 23
    curves = [{"pivots": [0, 1023], "segments": [
        {"method": "polynomial", "coefficients": [0, 1 << denominator]}]} for _ in range(3)]
    if case.startswith("mmr"):
        order = int(case[-1])
        # A positive dominant Cb term and small signed nonlinear contributions.
        # All requested orders are active, without forcing endpoint saturation.
        rows = [[1024, 1 << denominator, -1024, 1536, -2048, 1024, -512]]
        rows.extend([[256*(i+1), -512*(i+1), 768, -256, 128, -64, 32]
                     for i in range(order-1)])
        curves[1]["segments"] = [{"method": "mmr", "constant": 1 << 18,
                                  "coefficients": rows}]
    config = mapping.BaseMappingConfig.from_mappings(curves, bit_depth=10, denominator=denominator)
    correction = nlq.NLQConfig(10, denominator, 512, 2048, 0, 1048576)
    planes = [tuple((index*multiplier+offset) % 1024 for index in range(count))
              for multiplier, offset in ((37,17), (73,29), (101,43), (59,71))]
    return config, correction, planes, case != "disabled"


def checksum(stages):
    result = 14695981039346656037
    for row in zip(*stages):
        for value in row:
            word = value & 0xffffffff
            for shift in range(0, 32, 8):
                result = ((result ^ ((word >> shift) & 255))*1099511628211) & 0xffffffffffffffff
    return result


def limits():
    try:
        group = next(line.split(":", 2)[2].strip().lstrip("/")
                     for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0:"))
        directory = Path("/sys/fs/cgroup")/group
        result = {}
        for name in ("memory.max", "memory.swap.max", "memory.peak", "memory.swap.current", "memory.events"):
            raw = (directory/name).read_text().strip()
            result[name] = ({k: int(v) for k,v in (line.split() for line in raw.splitlines())}
                            if name == "memory.events" else raw if raw == "max" else int(raw))
        return result
    except (OSError, StopIteration):
        return None


def runtime():
    model = platform.processor()
    try:
        with Path("/proc/cpuinfo").open() as stream:
            fields = stream.read(65536).splitlines()
        model = next(line.split(":",1)[1].strip() for line in fields if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return dict(platform=platform.platform(), python=sys.version, cpu_model=model,
                process_affinity_cpu_count=len(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None)


def build(destination, *, compiler="cc"):
    destination = Path(destination).resolve()
    destination.mkdir()
    binary = destination/"libnative_kernel_bench.so"
    before = source_hashes()
    command = [compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-fno-lto", "-Wall",
               "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
               str(ROOT/"native_kernel_bench.c"), str(ROOT/"native_composer.c"), "-o", str(binary)]
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True).stdout
    compiled = subprocess.run(command, capture_output=True, text=True)
    if compiled.returncode:
        raise ValueError("benchmark compilation failed: " + compiled.stderr)
    if before != source_hashes():
        raise ValueError("source changed during compilation")
    record = dict(schema="yblod.native-kernel-build.v1", status="complete", source_sha256=before,
                  library_sha256=adapter.digest(binary), library=binary.name, command=command,
                  compiler_version=version, platform=platform.platform())
    with (destination/"build.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return binary


def load(binary):
    binary = Path(binary).resolve()
    raw, record = adapter._record(binary.parent/"build.json")
    if (record.get("schema") != "yblod.native-kernel-build.v1" or record.get("status") != "complete"
            or record.get("library") != binary.name or record.get("source_sha256") != source_hashes()
            or record.get("library_sha256") != adapter.digest(binary)):
        raise ValueError("benchmark build provenance mismatch")
    library = C.CDLL(str(binary))
    if (record["source_sha256"] != source_hashes() or record["library_sha256"] != adapter.digest(binary)
            or adapter._record(binary.parent/"build.json")[0] != raw):
        raise ValueError("benchmark build changed during load")
    version = library.yb_abi_version
    version.argtypes, version.restype = [], C.c_uint32
    if version() != 1:
        raise ValueError("composer ABI mismatch")
    for name, structure in (("mapping_config", adapter.Mapping), ("nlq_config", adapter.NLQ),
                            ("segment", adapter.Segment), ("component_mapping", adapter.Component),
                            ("kernel_measurement", Measurement)):
        query = getattr(library, "yb_sizeof_"+name)
        query.argtypes, query.restype = [], C.c_uint64
        if query() != C.sizeof(structure):
            raise ValueError("benchmark ABI size mismatch")
    u16, i32 = C.POINTER(C.c_uint16), C.POINTER(C.c_int32)
    function = library.yb_kernel_benchmark
    function.argtypes = [C.POINTER(adapter.Mapping), C.POINTER(adapter.NLQ), C.c_int32,
                        u16,u16,u16,u16,C.c_uint32,C.c_int32,C.c_int32,u16,i32,i32,u16,
                        C.c_uint32,C.POINTER(Measurement)]
    function.restype = C.c_int
    return library, function, record, hashlib.sha256(raw).hexdigest()


def run(binary, *, count=16384, iterations=128, repeats=5, require_memory_cap=False):
    adapter._integer(count, "count", 1, 65536)
    adapter._integer(iterations, "iterations", 1, 4096)
    adapter._integer(repeats, "repeats", 1, 20)
    if type(require_memory_cap) is not bool:
        raise ValueError("require_memory_cap must be boolean")
    if count*iterations*repeats*len(CASES) > 100_000_000:
        raise ValueError("aggregate timed sample budget exceeds 100 million")
    before = limits()
    if require_memory_cap and (before is None or before["memory.max"] != 512*1024*1024
                               or before["memory.swap.max"] != 0):
        raise ValueError("512 MiB/no-job-swap cgroup required")
    library, function, record, record_hash = load(binary)
    results = {}
    for case in CASES:
        config, correction, planes, enabled = fixture(case, count)
        _, compiled_config = adapter._mapping(config)
        _, compiled_correction = adapter._nlq(correction)
        inputs = [(C.c_uint16*count)(*plane) for plane in planes]
        outputs = [(kind*count)() for kind in (C.c_uint16,C.c_int32,C.c_int32,C.c_uint16)]
        expected_mapped = [mapping.map_sample(1, row, config) for row in zip(*planes[:3])]
        expected_residual = [nlq.correction(value, correction) if enabled else 0 for value in planes[3]]
        expected = [expected_mapped, expected_residual,
                    [a+b for a,b in zip(expected_mapped,expected_residual)],
                    [composition.compose_residual(a,b,12) for a,b in zip(expected_mapped,expected_residual)]]
        expected_checksum = checksum(expected)
        measurements = []
        for repeat in range(repeats):
            measured = Measurement()
            status = function(C.byref(compiled_config), C.byref(compiled_correction) if enabled else None,
                              1, *inputs[:3], inputs[3] if enabled else None, count, int(enabled), 12,
                              *outputs, iterations, C.byref(measured))
            if status:
                raise ValueError(f"{case}: benchmark status {status}")
            if [list(output) for output in outputs] != expected or measured.checksum != expected_checksum:
                raise ValueError(f"{case}: integer oracle mismatch")
            if measured.processed_samples != count*iterations:
                raise ValueError("incorrect processed sample count")
            if any(not math.isfinite(v) or v <= 0 for v in (measured.wall_seconds, measured.cpu_seconds)):
                raise ValueError("invalid timing")
            measurements.append(dict(repeat=repeat, wall_seconds=measured.wall_seconds,
                cpu_seconds=measured.cpu_seconds, processed_samples=measured.processed_samples,
                checksum=measured.checksum, all_four_stages_exact=True,
                million_component_samples_per_second=measured.processed_samples/measured.wall_seconds/1e6))
        rates = [row["million_component_samples_per_second"] for row in measurements]
        results[case] = dict(component=1, input_depth=10, output_depth=12, denominator=23,
            enabled_residual=enabled, count=count, iterations=iterations, repeats=measurements,
            input_plane_sha256={name: hashlib.sha256(struct.pack(f"<{count}H", *plane)).hexdigest()
                                for name,plane in zip(("guide_Y","Cb","Cr","EL"),planes)},
            expected_stage_sha256={name: hashlib.sha256(struct.pack(f"<{count}{code}", *plane)).hexdigest()
                for name,code,plane in zip(("mapped","residual","sum","reconstructed"),"HiiH",expected)},
            rate_summary=dict(minimum=min(rates),median=statistics.median(rates),maximum=max(rates)),
            fixture_scope="Explicit deterministic synthetic Y-guide/Cb/Cr/EL; same buffers reused.")
    after = limits()
    if require_memory_cap and (after["memory.swap.current"] != 0 or
            any(after["memory.events"].get(key,0) != before["memory.events"].get(key,0)
                for key in ("oom","oom_kill","oom_group_kill"))):
        raise ValueError("memory safety failure")
    if record["source_sha256"] != source_hashes():
        raise ValueError("source changed during benchmark")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(schema="yblod.native-kernel-benchmark.v1", status="complete", build_record=record,
        runtime=runtime(),
        build_record_sha256=record_hash, cases=results, timed_component_samples=count*iterations*repeats*len(CASES),
        limits_before=before, limits_after=after, process_maximum_rss_kib=rss/1024 if platform.system()=="Darwin" else rss,
        timing_scope="C chunk validation + arithmetic + caller-buffer writes; repeated same cached buffers; one FFI call per timed batch.",
        excluded_from_timing=["Python fixture generation and metadata encoding", "Python oracle comparisons",
            "one C warm-up per batch", "final C checksum", "output-file writes", "decoding/scaling/colour/HDMI"],
        limitations=["Component samples, not complete video pixels or frame rate.",
            "Fixed CPU synthetic workload; no steady-state playback, GPU throughput, or licensed-conformance claim.",
            "No LTO; separately compiled composer call executes each iteration. No production defaults changed.",
            "Build hashes detect ordinary mismatches, not malicious shared-library authentication."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("build")
    compile_parser.add_argument("destination")
    compile_parser.add_argument("--compiler", default="cc")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("library")
    run_parser.add_argument("output")
    run_parser.add_argument("--count", type=int, default=16384)
    run_parser.add_argument("--iterations", type=int, default=128)
    run_parser.add_argument("--repeats", type=int, default=5)
    run_parser.add_argument("--require-memory-cap", action="store_true")
    args = parser.parse_args()
    if args.command == "build":
        print(build(args.destination, compiler=args.compiler))
    else:
        output = Path(args.output)
        if output.exists():
            raise FileExistsError(output)
        report = run(args.library, count=args.count, iterations=args.iterations,
                     repeats=args.repeats, require_memory_cap=args.require_memory_cap)
        with output.open("x") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        print(json.dumps({case: value["rate_summary"] for case,value in report["cases"].items()}))


if __name__ == "__main__":
    main()
