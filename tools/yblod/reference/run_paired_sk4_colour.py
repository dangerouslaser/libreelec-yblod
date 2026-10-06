#!/usr/bin/env python3
"""CPU-only same-colour-backend integer/FP32 comparisons under a hard scope.

Raw reports remain private. The baseline reconstructed planes are real outputs,
not a copy of old transport bytes. No device access or new captures occur.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from gpu_dump_colour_adapter import adapt, read_json, sha


def resources():
    line = next(x for x in Path("/proc/self/cgroup").read_text().splitlines() if x.startswith("0::"))
    group = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
    return {n: (group / n).read_text().strip() for n in
        ("memory.max", "memory.swap.max", "memory.swap.current", "memory.events", "memory.peak", "cpu.max")}


def guard(snapshot):
    if snapshot["memory.max"] != "536870912" or snapshot["memory.swap.max"] != "0" or snapshot["memory.swap.current"] != "0":
        raise ValueError("hard512MiB/no-swap scope required")
    if any(int(v) for k, v in (x.split() for x in snapshot["memory.events"].splitlines())
           if k in ("high", "max", "oom", "oom_kill")):
        raise ValueError("memory pressure/event detected")
    quota, period = snapshot["cpu.max"].split()
    if quota == "max" or int(quota) > int(period):
        raise ValueError("CPU quota at most one core required")


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def main():
    p = argparse.ArgumentParser()
    for n in ("repo", "baseline", "historical-output", "extraction", "fixture", "dump", "probe-report",
              "native-library", "capture-directory", "destination"):
        p.add_argument("--" + n, required=True, type=Path)
    a = p.parse_args()
    for n in vars(a):
        setattr(a, n, getattr(a, n).resolve())
    if a.destination.stat().st_mode & 0o077 or any(a.destination.iterdir()):
        raise ValueError("fresh private destination required")
    before = resources()
    guard(before)
    sys.path.insert(0, str(a.repo / "tools/yblod/reference"))
    import colour_metadata
    import colour_frame
    import compare_colour_frame
    historical = read_json(a.historical_output / "output.json")
    if historical.get("policy") != "direct":
        raise ValueError("explicit historical direct policy required")
    reconstructed = a.destination / "fp32-reconstructed"
    adapt(a.repo, a.baseline, a.extraction, a.fixture, a.dump, a.probe_report, reconstructed)
    choices = {k: historical[k] for k in ("target_ycc", "target_lms", "target_offset")}
    choices.update(pq_policy="extend-positive-negative-to-zero", outside_codes=[0, 2048, 2048], code_scale=4096)
    write_json(a.destination / "target-settings.json", choices)
    outputs = {}
    for label, result in (("integer", a.baseline), ("fp32", reconstructed)):
        config = a.destination / (label + "-configuration.json")
        colour_metadata.make_configuration(result, a.extraction, config, **choices)
        output = a.destination / (label + "-native-colour")
        outputs[label] = colour_frame.run(result, config, output, extraction=a.extraction,
            backend="native", native_library=a.native_library)
        guard(resources())
        print(label + " native C colour conversion complete.", flush=True)
    # Explicit compatibility view of the just-computed native baseline, not
    # historical NumPy output. Only the two actual transport stages are linked.
    view = a.destination / "integer-native-transport-view"
    view.mkdir(mode=0o700)
    integer = outputs["integer"]
    stages = {}
    for key in ("transport_ipt444.u16le", "unembedded_tunnel.rgb8"):
        record = integer["stages"][key]
        os.link(a.destination / "integer-native-colour" / record["file"], view / record["file"])
        stages[key.split(".")[0]] = dict(file=record["file"], sha256=record["sha256"],
                                        shape=[integer["height"], integer["width"], 3])
    wrapper = dict(schema="yblod.output-reference.v1", status="complete",
        scope="compatibility view of actual integer planes converted with same native C backend; not historical producer",
        identity=integer["identity"], width=integer["width"], height=integer["height"],
        active_rectangle=integer["configuration"]["active_rectangle"], policy="direct",
        chroma_expansion="bilinear-left-edge-replicated-float64",
        source_dm=integer["configuration"]["source_dm"],
        rpu_sha256=integer["source_provenance"]["rpu_json_sha256"], stages=stages,
        actual_native_colour_report_sha256=sha(a.destination / "integer-native-colour" / "output.json"),
        **{k: integer["configuration"][k] for k in ("target_ycc", "target_lms", "target_offset")})
    write_json(view / "output.json", wrapper)
    # Isolate historical NumPy-vs-native colour rounding from composer deltas.
    sanity = compare_colour_frame.compare(a.destination / "integer-native-colour", a.historical_output)
    write_json(a.destination / "historical-colour-backend-check.json", sanity)
    print("Historical colour-backend check complete.", flush=True)
    runs = []
    for cycle in range(3):
        for reread in ("first", "second"):
            name = f"cycle-{cycle:02d}-{reread}.rgb"
            report = compare_colour_frame.compare(a.destination / "fp32-native-colour", view,
                capture=a.capture_directory / name, capture_identity=a.capture_directory / "identity.json")
            write_json(a.destination / (name + "-comparison-private.json"), report)
            runs.append(dict(capture_label=name, channels=report["comparisons"]))
            guard(resources())
            print(name + " paired SK4 comparison complete.", flush=True)
    after = resources()
    guard(after)
    summary = dict(schema="yblod.paired-sk4-native-colour-checkpoint.v1", status="complete",
        scope="same native C colour policy; integer vs FP32 composer effect on SK4 transport disagreement; historical prepared inputs, not live display accuracy",
        before=before, after=after, comparisons=runs,
        historical_colour_backend_check=sanity["comparisons"],
        implementation_sha256=sha(Path(__file__)), adapter_sha256=sha(Path(__file__).with_name("gpu_dump_colour_adapter.py")))
    write_json(a.destination / "summary-private.json", summary)
    print("Paired comparison complete; private reports retained.", flush=True)


if __name__ == "__main__":
    main()
