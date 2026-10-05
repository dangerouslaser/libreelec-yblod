"""Exact affine-coordinate probes, independent of movie pixels/filter taps."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from hardware_scaling_run import FLAGS, _invocation
from hardware_scaling_vectors import check_identity
from scaling_probe import CHANNELS, pack_p010, unpack_p010

BASES = {"Y": 256, "Cb": 384, "Cr": 512}


def affine_planes(axis):
    if axis not in ("x", "y", "x-desc", "y-desc"):
        raise ValueError("choose x or y")
    descending = axis.endswith("-desc")
    # Exactly eight codes per native sample, not a staircase or rounded ramp.
    # Each component has its own coordinate; this is not a common colour field.
    return {c: [[BASES[c] + 8 * ((63 if c == "Y" else 31) - (x if axis[0] == "x" else y)
                               if descending else (x if axis[0] == "x" else y))
                 for x in range(64 if c == "Y" else 32)]
                for y in range(64 if c == "Y" else 32)] for c in CHANNELS}


def analyse(axis, output):
    if axis not in ("x", "y", "x-desc", "y-desc"):
        raise ValueError("choose x or y")
    descending = axis.endswith("-desc")
    coordinate_axis = axis[0]
    planes = unpack_p010(output, 128, 128)
    channels = {}
    for c in CHANNELS:
        samples = planes[c]
        h, w = len(samples), len(samples[0])
        errors, steps = [], []
        parity_errors = {"0": [], "1": []}
        for y in range(16, h - 16):
            for x in range(16, w - 16):
                m = x if coordinate_axis == "x" else y
                # Independent first-moment prediction, with no rounding ties:
                # horizontal m/2; vertical m/2-1/4; source slope8.
                slope = -4 if descending else 4
                base = BASES[c] + (8 * (h // 2 - 1) if descending else 0)
                expected = base + slope * m - (slope // 2 if coordinate_axis == "y" else 0)
                error = samples[y][x] - expected
                errors.append(error)
                parity_errors[str(m % 2)].append(error)
                if (x + 1 < w - 16 if coordinate_axis == "x" else y + 1 < h - 16):
                    steps.append((samples[y][x + 1] if coordinate_axis == "x" else samples[y + 1][x]) - samples[y][x])
        channels[c] = {"interior_samples": len(errors), "interior_error_values": sorted(set(errors)),
                       "interior_step_values": sorted(set(steps)), "expected_step": -4 if descending else 4,
                       "axis_parity_error_values": {p: sorted(set(e)) for p, e in parity_errors.items()},
                       "mean_signed_error": sum(errors) / len(errors),
                       "maximum_absolute_error": max(abs(e) for e in errors),
                       "margin_output_samples": 16}
    return {"axis": axis, "channels": channels,
            "interpretation": "logical sample-index registration versus Annex B first moments; not licensed Dolby geometry or a proposed correction"}


def run(binary, destination, device="/dev/dri/renderD128"):
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    binary = Path(binary).resolve()
    report = {"schema": "yblod.hardware-affine-phase.v1", "status": "failed",
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "hardware_engine_verified": False, "invocations": [], "results": {}}

    def call(axis, mode, size, repetition):
        stem = f"{axis}-{mode}-{size}-{repetition}"
        output = root / (stem + ".p010")
        argv = [str(binary), device, str(root / (axis + "-input.p010")), str(output),
                "64", "64", str(size), str(size), mode]
        result = subprocess.run(argv, capture_output=True, timeout=30)
        entry = {"argv": argv, "exit_status": result.returncode}
        report["invocations"].append(entry)
        for kind, data in (("stdout", result.stdout), ("stderr", result.stderr)):
            path = root / (stem + "." + kind + ".log")
            with path.open("xb") as handle:
                handle.write(data)
            entry[kind] = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest()}
        if result.returncode:
            raise ValueError("probe invocation failed")
        entry["invocation"] = _invocation(result.stdout, [64, 64], [size, size], mode)
        data = output.read_bytes()
        entry["output_sha256"] = hashlib.sha256(data).hexdigest()
        return data, entry

    try:
        inputs = {axis: affine_planes(axis) for axis in ("x", "y", "x-desc", "y-desc")}
        for axis, planes in inputs.items():
            with (root / (axis + "-input.p010")).open("xb") as handle:
                handle.write(pack_p010(planes))
        for axis, planes in inputs.items():
            for mode in ("copy", "default"):
                data, entry = call(axis, mode, 64, 0)
                entry["identity"] = check_identity(planes, data)
                if not entry["identity"]["exact"]:
                    raise ValueError("affine native-code identity failed")
        for axis in inputs:
            results = report["results"].setdefault(axis, {})
            for mode in FLAGS:
                data, first = call(axis, mode, 128, 0)
                repeated, second = call(axis, mode, 128, 1)
                # Validate both downloads, not just their hashes.
                unpack_p010(repeated, 128, 128)
                value = analyse(axis, data)
                value.update(output_sha256=first["output_sha256"], repeat_sha256=second["output_sha256"],
                             repeat_stable=data == repeated)
                results[mode] = value
                if not value["repeat_stable"]:
                    raise ValueError("affine repeated output differs")
        report["status"] = "complete"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    with (root / "phase-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    args = parser.parse_args()
    result = run(args.binary, args.destination, args.device)
    raise SystemExit(result["status"] != "complete")
