#!/usr/bin/env python3
"""Summarize forward sampling reports without image reads, ranking or pooling.

Reports must share implementations, runtime, variant definitions and held-fixed
policies. Source metadata may differ. Declared hash syntax, embedded-source
hashes and measurement partitions are checked; underlying image/helper/source
integrity remains the original runner's responsibility, not something this
report-only tool can independently repeat.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from extract_frame import digest, save_json
from summarize_cases import read_json

VARIANTS = ("linear-left", "cubic-left", "linear-top-control", "linear-bottom-control")
CHANNELS = ("I", "P", "T")
GROUPS = ("all", "even_row", "odd_row", "smooth_le_4", "intermediate_5_16", "edge_gt_16")
SELECTED_GROUPS = ("all", "smooth_le_4", "edge_gt_16")
COMPARISONS = ("versus_capture", "minus_baseline")
METRICS = ("mean_signed_codes", "mean_absolute_codes", "rmse_codes", "maximum_absolute_codes")


def sha(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"invalid {name} SHA-256")


def integer(value, name, low=0):
    if type(value) is not int or value < low:
        raise ValueError(f"invalid {name}")
    return value


def metric_group(group):
    n = integer(group["samples"], "sample count")
    for key in ("negative", "zero", "positive"):
        integer(group[key], key)
    if sum(group[k] for k in ("negative", "zero", "positive")) != n:
        raise ValueError("signed sample counts do not partition group")
    peak = integer(group["maximum_absolute_codes"], "maximum absolute code difference")
    if peak > 4095:
        raise ValueError("code difference exceeds 12-bit range")
    if not n:
        if peak or any(group[k] is not None for k in METRICS[:3]):
            raise ValueError("empty group has nonempty metrics")
        return
    signed, absolute, rms = [group[k] for k in METRICS[:3]]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (signed, absolute, rms)):
        raise ValueError("non-finite or invalid metric")
    if not (abs(signed) <= absolute + 1e-9 and 0 <= absolute <= rms + 1e-9 and rms <= peak + 1e-9):
        raise ValueError("inconsistent mean/RMSE/maximum metrics")
    if (group["zero"] == n) != (peak == 0):
        raise ValueError("zero count and maximum differ")
    if absolute*n + 1e-6 < n-group["zero"]:
        raise ValueError("integer differences smaller than nonzero sample count")


def partition(groups, keys):
    all_group = groups["all"]
    for count in ("samples", "negative", "zero", "positive"):
        if sum(groups[key][count] for key in keys) != all_group[count]:
            raise ValueError("group counts do not partition all samples")
    if max(groups[key]["maximum_absolute_codes"] for key in keys) != all_group["maximum_absolute_codes"]:
        raise ValueError("group maxima do not match all-sample maximum")
    for metric, power in (("mean_signed_codes", 1), ("mean_absolute_codes", 1), ("rmse_codes", 2)):
        reconstructed = sum((groups[key][metric] or 0)**power * groups[key]["samples"] for key in keys)
        expected = all_group[metric]**power * all_group["samples"]
        if not math.isclose(reconstructed, expected, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError("group metrics do not partition all-sample metrics")


def validate(path):
    path = Path(path).resolve()
    report = read_json(path)
    if report["schema"] != "yblod.forward-sampling-experiment.v1" or report["status"] != "complete":
        raise ValueError("completed forward sampling report required")
    w, h = integer(report["width"], "width", 2), integer(report["height"], "height", 2)
    rectangle = report["active_rectangle"]
    if not isinstance(rectangle, list) or len(rectangle) != 4:
        raise ValueError("invalid active rectangle")
    l, t, r, b = [integer(v, "rectangle coordinate") for v in rectangle]
    if not (l < r <= w and t < b <= h) or w % 2 or h % 2 or l % 2 or r % 2:
        raise ValueError("invalid active rectangle or frame geometry")
    identity = report["identity"]
    frame_id = identity["frame_id"]
    if not isinstance(frame_id, str) or not frame_id:
        raise ValueError("invalid frame identity")
    if type(identity["pts"]) is not int or not isinstance(identity["time_base"], list) or len(identity["time_base"]) != 2:
        raise ValueError("invalid frame timestamp")
    for value in identity["time_base"]:
        integer(value, "time-base member", 1)
    if not isinstance(report["identity_basis"], str) or not report["identity_basis"]:
        raise ValueError("missing capture association basis")
    for key in ("composer_report_sha256", "rpu_sha256", "capture_sha256"):
        sha(report[key], key)
    provenance = report["source_provenance"]
    for key in ("output_report_sha256", "comparison_report_sha256", "compared_tunnel_sha256"):
        sha(provenance[key], key)
    baseline = report["baseline"]
    if (baseline["variant"] != "linear-left" or baseline["byte_identical"] is not True
            or type(baseline["verified_bytes"]) is not int or baseline["verified_bytes"] != w*h*3
            or baseline["tunnel_sha256"] != provenance["compared_tunnel_sha256"]):
        raise ValueError("baseline full-frame byte verification missing or inconsistent")
    metadata = report["metadata"]
    if (metadata["packets"] != 2 or metadata["copies_per_packet"] != 3
            or metadata["all_crc_valid"] is not True or metadata["copies_identical"] is not True):
        raise ValueError("capture metadata validation incomplete")
    if report["held_fixed"]["policy"] != "direct":
        raise ValueError("non-direct colour policy")
    runtime = report["runtime"]
    if any(not isinstance(runtime[key], str) or not runtime[key] for key in ("numpy_version", "python_version")):
        raise ValueError("missing numerical runtime version")
    implementations = report["implementation"]
    if set(implementations) != {"experiment", "geometry", "colour_conversion_and_packing"}:
        raise ValueError("implementation set differs")
    for name, record in implementations.items():
        sha(record["sha256"], name)
        if not isinstance(record["source"], str) or hashlib.sha256(record["source"].encode()).hexdigest() != record["sha256"]:
            raise ValueError("embedded implementation source hash mismatch")
    helpers = report["helper_implementations"]
    required_helpers = {"diagnose_frame", "compare_output", "dvtunnel", "dvlms", "inverse_stage", "summarize_cases",
                        "extract_frame", "import_rpu", "inspect_composition", "reference"}
    if set(helpers) != required_helpers:
        raise ValueError("helper implementation set differs")
    for name, record in helpers.items():
        sha(record["sha256"], name)
    if set(report["variants"]) != set(VARIANTS):
        raise ValueError("unexpected variant set")
    fixed_counts = {}
    for variant, record in report["variants"].items():
        configuration = record["configuration"]
        if (configuration["schema"] != "yblod.chroma-geometry-experiment.v1" or configuration["variant"] != variant
                or configuration["invalid_geometry_control"] is not variant.endswith("-control")
                or configuration["production_choice"] is not False):
            raise ValueError("variant/control configuration mismatch")
        comparisons = record["comparisons"]
        if set(comparisons) != set(COMPARISONS):
            raise ValueError("unexpected comparison set")
        for comparison, channels in comparisons.items():
            if set(channels) != set(CHANNELS):
                raise ValueError("unexpected channel set")
            for channel, groups in channels.items():
                if set(groups) != set(GROUPS):
                    raise ValueError("unexpected group set")
                divisor = 1 if channel == "I" else 2
                width = (r-l)//divisor
                evens = (b+1)//2 - (t+1)//2
                expected = {"all": width*(b-t), "even_row": width*evens, "odd_row": width*(b-t-evens)}
                for group, metrics in groups.items():
                    metric_group(metrics)
                    count = metrics["samples"]
                    if group in expected and count != expected[group]:
                        raise ValueError("sample count differs from absolute geometry/parity")
                    key = channel, group
                    if key in fixed_counts and fixed_counts[key] != count:
                        raise ValueError("capture masks differ across variants/comparisons")
                    fixed_counts[key] = count
                    if variant == "linear-left" and comparison == "minus_baseline" and metrics["maximum_absolute_codes"]:
                        raise ValueError("baseline changed relative to itself")
                partition(groups, ("even_row", "odd_row"))
                partition(groups, ("smooth_le_4", "intermediate_5_16", "edge_gt_16"))
    return report, digest(path)


def brief(groups):
    selected = {name: {key: groups[name][key] for key in ("samples",) + METRICS} for name in SELECTED_GROUPS}
    even, odd = groups["even_row"]["mean_signed_codes"], groups["odd_row"]["mean_signed_codes"]
    return {"groups": selected, "even_row_mean_signed_codes": even, "odd_row_mean_signed_codes": odd,
            "even_minus_odd_mean_signed_codes": even-odd if even is not None and odd is not None else None}


def summarize(paths):
    cases, seen, shared = [], set(), None
    for path in paths:
        report, report_hash = validate(path)
        identity_key = report["identity"]["frame_id"]
        if identity_key in seen:
            raise ValueError("duplicate frame identity")
        seen.add(identity_key)
        common = {"runtime": report["runtime"], "held_fixed": report["held_fixed"],
                  "implementations": {name: {key: value for key, value in record.items() if key != "source"}
                                      for name, record in report["implementation"].items()},
                  "helper_implementations": report["helper_implementations"],
                  "variant_configurations": {variant: report["variants"][variant]["configuration"] for variant in VARIANTS},
                  "group_definitions": report["group_definitions"], "processing_strip_rows": report["processing_strip_rows"]}
        if shared is None:
            shared = common
        elif shared != common:
            differing = [key for key in common if common[key] != shared[key]]
            raise ValueError("cases differ in held-fixed implementation/policy: " + ", ".join(differing))
        baseline = report["variants"]["linear-left"]["comparisons"]["versus_capture"]
        variants = {}
        for variant in VARIANTS:
            record = report["variants"][variant]
            current = record["comparisons"]["versus_capture"]
            changes = {channel: {group: {metric: current[channel][group][metric]-baseline[channel][group][metric]
                                                 if current[channel][group]["samples"] else None
                                              for metric in METRICS[1:]}
                                  for group in SELECTED_GROUPS} for channel in CHANNELS}
            variants[variant] = {
                "invalid_geometry_control": record["configuration"]["invalid_geometry_control"],
                "versus_capture": {channel: brief(current[channel]) for channel in CHANNELS},
                "processing_change_minus_linear_baseline": {channel: brief(record["comparisons"]["minus_baseline"][channel]) for channel in CHANNELS},
                "error_metric_change_from_linear_baseline": changes}
        cases.append({"identity": report["identity"], "identity_basis": report["identity_basis"],
                      "report_file": Path(path).name, "report_sha256": report_hash,
                      "capture_sha256": report["capture_sha256"], "composer_report_sha256": report["composer_report_sha256"],
                      "rpu_sha256": report["rpu_sha256"], "active_rectangle": report["active_rectangle"],
                      "baseline_verified_bytes": report["baseline"]["verified_bytes"], "variants": variants})
    if not cases:
        raise ValueError("at least one case required")
    return {"schema": "yblod.forward-sampling-summary.v1", "status": "complete", "case_count": len(cases),
            "scope": "Per-frame transport-code experiment; not perceptual accuracy, conformance, ranking or production filter selection",
            "interpretation": "Negative error-metric changes mean smaller differences to this capture, not greater correctness. Processing-change values instead measure what the variant changed relative to the baseline.",
            "controls": "linear-top-control and linear-bottom-control intentionally violate the prepared-left geometry; neither is a production candidate.",
            "validation": "Report files and embedded source text are hashed; declared baseline verification, measurement partitions and shared configuration are checked. No source video or image bytes are reread.",
            "shared": shared, "cases": cases, "implementation_sha256": digest(Path(__file__))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.case)
        save_json(args.output, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"sampling summary: {error}\n")
    print(json.dumps({"output": str(args.output), "case_count": report["case_count"]}))


if __name__ == "__main__":
    main()
