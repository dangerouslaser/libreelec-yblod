"""Diagnostic requested input/output chroma-siting matrix, synthetic-only.

Identical sample bytes with a different input-siting declaration represent a
different physical grid, NOT the same physical picture. These four requests
measure driver responses; they neither prove a flag was honored nor choose a
Dolby-correct geometry. No output fitting, correction, or movie pixels.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import hardware_phase_check as phase
import hardware_scaling_vectors as vectors
import scaling_probe
from hardware_scaling_vectors import check_identity, patterns
from scaling_probe import CHANNELS, pack_p010, unpack_p010

SITING = {"left": 6, "top-left": 5}
CONFIGURATIONS = tuple((i, o) for i in SITING for o in SITING)
AXES = ("x", "y", "x-desc", "y-desc")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_invocation(stdout, size, input_siting, output_siting, copy=False):
    value = json.loads(stdout)
    expected = {"schema": "yblod.vaapi-scaler-invocation.v1", "status": "complete",
                "input_size": [64, 64], "output_size": [size, size], "filter_flags": 0,
                "input_chroma_siting": None if copy else SITING[input_siting],
                "output_chroma_siting": None if copy else SITING[output_siting],
                "colour_standard": None if copy else 12, "colour_range": None if copy else 2,
                "vpp_submitted": not copy, "hardware_engine_verified": False}
    for key, item in expected.items():
        actual = value.get(key)
        if actual != item or type(actual) is not type(item):
            raise ValueError(f"invalid siting invocation declaration: {key}")
    if not isinstance(value.get("vendor"), str) or not value["vendor"].strip():
        raise ValueError("missing VA vendor")
    version = value.get("va_version")
    if not isinstance(version, list) or len(version) != 2 or any(type(v) is not int or v < 0 for v in version):
        raise ValueError("missing VA version")
    return value


def delta_metrics(actual, baseline):
    """Code differences versus one declared configuration, never a fitted shift."""
    def metrics(errors):
        return {"samples": len(errors), "different": sum(e != 0 for e in errors),
                "error_values": sorted(set(errors)),
                "mean_signed_error": sum(errors)/len(errors),
                "mean_absolute_error": sum(abs(e) for e in errors)/len(errors),
                "maximum_absolute_error": max(abs(e) for e in errors)}
    result = {}
    for c in CHANNELS:
        errors = [[a-b for a, b in zip(arow, brow)] for arow, brow in zip(actual[c], baseline[c])]
        result[c] = dict(metrics([e for row in errors for e in row]),
                         row_parity={str(p): metrics([e for row in errors[p::2] for e in row]) for p in (0, 1)},
                         column_parity={str(p): metrics([e for row in errors for e in row[p::2]]) for p in (0, 1)})
    return result


def run(binary, destination, device="/dev/dri/renderD128", repeats=2):
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    report = {"schema": "yblod.hardware-chroma-siting-matrix.v1", "status": "failed",
              "hardware_engine_verified": False, "invocations": [], "results": {},
              "source_sha256": sha(Path(__file__).read_bytes()),
              "phase_helper_sha256": sha(Path(phase.__file__).read_bytes()),
              "vectors_helper_sha256": sha(Path(vectors.__file__).read_bytes()),
              "transport_helper_sha256": sha(Path(scaling_probe.__file__).read_bytes()),
              "kernel": list(os.uname()), "device": str(device),
              "interpretation": "changing input siting reinterprets identical bytes on a different physical grid; declared configuration diagnostics, not flag-honoring proof or Dolby geometry"}

    def call(name, size, input_siting, output_siting, repetition, copy=False):
        mode = "copy" if copy else "default"
        stem = f"{mode}-{input_siting}-to-{output_siting}-{name}-{size}-{repetition}"
        output = root/f"{stem}.p010"
        argv = [str(executable), str(device), str(root/f"{name}-input.p010"), str(output),
                "64", "64", str(size), str(size), mode]
        if not copy:
            argv.extend(["--input-chroma", input_siting, "--output-chroma", output_siting])
        entry = {"argv": argv, "pattern": name, "output_size": [size, size],
                 "requested_input_chroma": input_siting, "requested_output_chroma": output_siting,
                 "copy": copy, "repetition": repetition, "output_file": output.name}
        report["invocations"].append(entry)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
            stdout, stderr = result.stdout, result.stderr
            entry["exit_status"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            entry.update(exit_status=None, timed_out=True)
        except OSError as error:
            stdout, stderr = b"", str(error).encode()
            entry.update(exit_status=None, spawn_error=type(error).__name__)
        for kind, data in (("stdout", stdout), ("stderr", stderr)):
            path = root/f"{stem}.{kind}.log"
            with path.open("xb") as handle:
                handle.write(data)
            entry[kind] = {"file": path.name, "sha256": sha(data), "bytes": len(data)}
        if output.exists(): entry["output_sha256"] = sha(output.read_bytes())
        if entry["exit_status"] != 0: raise ValueError("siting probe failed or timed out")
        entry["invocation"] = validate_invocation(stdout, size, input_siting, output_siting, copy)
        data = output.read_bytes()
        unpack_p010(data, size, size)
        return data, entry

    try:
        if type(repeats) is not int or not 2 <= repeats <= 4:
            raise ValueError("between 2 and 4 repeats required")
        executable = Path(binary).resolve()
        report.update(binary=str(executable), binary_sha256=sha(executable.read_bytes()), repeats=repeats)
        constants = patterns()["neutral"], patterns()["channel-tags"]
        inputs = {"neutral": constants[0], "channel-tags": constants[1],
                  **{axis: phase.affine_planes(axis) for axis in AXES}}
        report["inputs"] = {}
        for name, planes in inputs.items():
            data = pack_p010(planes)
            with (root/f"{name}-input.p010").open("xb") as handle: handle.write(data)
            report["inputs"][name] = {"file": f"{name}-input.p010", "sha256": sha(data)}
        for name, planes in inputs.items():
            data, entry = call(name, 64, "left", "left", 0, copy=True)
            entry["identity"] = check_identity(planes, data)
            if not entry["identity"]["exact"]: raise ValueError("copy native-code identity failed")
        report["copy_checks_complete"] = True
        baselines = {}
        # Complete every 1:1 request (including both same-grid identity gates)
        # before submitting any 2x scaling request.
        for size in (64, 128):
            for input_siting, output_siting in CONFIGURATIONS:
                key = f"{input_siting}-to-{output_siting}"
                configuration = report["results"].setdefault(key, {})
                cases = configuration.setdefault(str(size), {})
                for name, planes in inputs.items():
                    outputs = [call(name, size, input_siting, output_siting, repetition)[0]
                               for repetition in range(repeats)]
                    actual = unpack_p010(outputs[0], size, size)
                    value = {"repeat_sha256": [sha(data) for data in outputs],
                             "repeat_stable": all(data == outputs[0] for data in outputs),
                             "same_grid": input_siting == output_siting}
                    cases[name] = value
                    if not value["repeat_stable"]: raise ValueError("siting repeated output differs")
                    if size == 64:
                        value["identity"] = check_identity(planes, outputs[0])
                        if value["same_grid"] and not value["identity"]["exact"]:
                            raise ValueError("same-grid 1:1 VPP identity failed")
                    if name in ("neutral", "channel-tags"):
                        expected = {c: [[planes[c][0][0]]*(size if c == "Y" else size//2)
                                        for _ in range(size if c == "Y" else size//2)] for c in CHANNELS}
                        value["constant_codes_preserved"] = actual == expected
                        if not value["constant_codes_preserved"]: raise ValueError("constant/channel-tag codes changed")
                    elif size == 128:
                        value["affine_first_moment"] = phase.analyse(name, outputs[0])
                    baseline = baselines.setdefault((size, name), actual)
                    value["differences_from_left_to_left"] = delta_metrics(actual, baseline)
                    value["luma_identical_across_siting_requests"] = actual["Y"] == baseline["Y"]
                    if not value["luma_identical_across_siting_requests"]:
                        raise ValueError("luma changed across chroma-siting requests")
        report["status"] = "complete"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    with (root/"chroma-siting-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    result = run(args.binary, args.destination, args.device, args.repeats)
    raise SystemExit(result["status"] != "complete")
