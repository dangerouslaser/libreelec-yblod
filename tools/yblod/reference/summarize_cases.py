#!/usr/bin/env python3
"""Summarize matched direct/bounded SK4 comparisons without pooling frames.

Each --case names a direct output directory and an rgb-bound-diagnostic output
directory, both containing output.json and sk4.json. Reads small reports and
streams the compared tunnel's hash with a 1 MiB buffer; never loads an image.
The supplied capture association is evidence, not an independently verified
frame timestamp. Scores describe transport codes, not perceived picture quality.
"""
import argparse
import json
import math
from pathlib import Path

from extract_frame import digest, save_json


METRICS = ("mean_absolute_codes", "rmse_codes", "maximum_absolute_codes",
           "over_sixteen_codes_percent")
MATCH_OUTPUT = ("identity", "width", "height", "active_rectangle", "target_ycc",
                "target_lms", "target_offset", "composer_report_sha256", "rpu_sha256",
                "chroma_expansion", "pq_domain", "quantization", "transport_sampling",
                "source_dm", "implementation_sha256", "numpy_version")
MATCH_COMPARISON = ("capture_sha256", "identity_file_sha256", "identity_basis",
                    "active_rectangle", "implementation_sha256")


def read_json(path):
    def reject(value):
        raise ValueError(f"non-finite JSON value: {value}")
    return json.loads(path.read_text(), parse_constant=reject)


def checked(directory, policy):
    directory = Path(directory).resolve()
    info = read_json(directory / "output.json")
    comparison = read_json(directory / "sk4.json")
    if (info["schema"] != "yblod.output-reference.v1" or info["status"] != "complete"
            or info["policy"] != policy or comparison["policy"] != policy):
        raise ValueError("wrong output schema, status, or policy")
    identity = info["identity"]
    if (not isinstance(identity["frame_id"], str) or not identity["frame_id"]
            or type(identity["pts"]) is not int
            or not isinstance(identity["time_base"], list) or len(identity["time_base"]) != 2
            or any(type(x) is not int or x <= 0 for x in identity["time_base"])):
        raise ValueError("invalid frame identity")
    for report, keys in ((info, ("composer_report_sha256", "rpu_sha256", "implementation_sha256")),
                         (comparison, ("capture_sha256", "identity_file_sha256",
                                       "output_report_sha256", "implementation_sha256"))):
        for key in keys:
            value = report[key]
            if (not isinstance(value, str) or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError(f"invalid {key}")
    if comparison["output_report_sha256"] != digest(directory / "output.json"):
        raise ValueError("comparison output report hash mismatch")
    if (comparison["identity"] != info["identity"]
            or comparison["active_rectangle"] != info["active_rectangle"]
            or comparison["transport_matrices_equal"] is not True
            or comparison["metadata_first_copy_crc"] != [True, True]):
        raise ValueError("comparison identity, rectangle, or transport validation mismatch")
    width, height = info["width"], info["height"]
    l, t, r, b = info["active_rectangle"]
    if (any(type(x) is not int for x in (width, height, l, t, r, b))
            or not 0 <= l < r <= width or not 0 <= t < b <= height
            or width % 2 or l % 2 or r % 2):
        raise ValueError("invalid frame dimensions or active rectangle")
    record = info["stages"]["unembedded_tunnel"]
    tunnel = (directory / record["file"]).resolve()
    if (not tunnel.is_relative_to(directory) or record["shape"] != [height, width, 3]
            or tunnel.stat().st_size != width * height * 3
            or digest(tunnel) != record["sha256"]):
        raise ValueError("compared tunnel integrity failed")
    if set(comparison["channels"]) != {"I", "P", "T"}:
        raise ValueError("expected I, P, T channels")
    for name, channel in comparison["channels"].items():
        expected = (r - l) * (b - t) // (1 if name == "I" else 2)
        if type(channel["samples"]) is not int or channel["samples"] != expected:
            raise ValueError("comparison sample count differs from rectangle")
        for key in METRICS:
            value = channel[key]
            maximum = 100 if key.endswith("percent") else 4095
            if (type(value) not in (float, int) or not math.isfinite(value)
                    or not 0 <= value <= maximum):
                raise ValueError("invalid comparison metric")
        if (channel["mean_absolute_codes"] > channel["rmse_codes"] + 1e-9
                or channel["rmse_codes"] > channel["maximum_absolute_codes"] + 1e-9):
            raise ValueError("inconsistent comparison metrics")
    return info, comparison, {
        "directory": str(directory), "output_report_sha256": digest(directory / "output.json"),
        "comparison_report_sha256": digest(directory / "sk4.json"),
        "compared_tunnel_sha256": record["sha256"],
    }


def summarize(cases):
    results, seen = [], set()
    for direct_directory, bound_directory in cases:
        direct, baseline, direct_sources = checked(direct_directory, "direct")
        bounded, candidate, bound_sources = checked(bound_directory, "rgb-bound-diagnostic")
        for key in MATCH_OUTPUT:
            if direct[key] != bounded[key]:
                raise ValueError(f"paired output mismatch: {key}")
        for key in MATCH_COMPARISON:
            if baseline[key] != candidate[key]:
                raise ValueError(f"paired comparison mismatch: {key}")
        identity_key = direct["identity"]["frame_id"]
        if identity_key in seen:
            raise ValueError("duplicate frame identity in case list")
        seen.add(identity_key)
        channels = {}
        for name in ("I", "P", "T"):
            a, b = baseline["channels"][name], candidate["channels"][name]
            change = {metric: b[metric] - a[metric] for metric in METRICS}
            channels[name] = {
                "samples": a["samples"],
                "direct": {metric: a[metric] for metric in METRICS},
                "rgb_bound_diagnostic": {metric: b[metric] for metric in METRICS},
                "change_bound_minus_direct": change,
                "metrics_increased": [metric for metric in METRICS if change[metric] > 0],
            }
        results.append({
            "identity": direct["identity"], "active_rectangle": direct["active_rectangle"],
            "capture_sha256": baseline["capture_sha256"],
            "identity_file_sha256": baseline["identity_file_sha256"],
            "identity_basis": baseline["identity_basis"],
            "composer_report_sha256": direct["composer_report_sha256"],
            "rpu_sha256": direct["rpu_sha256"],
            "target_coordinates": {key: direct[key] for key in ("target_ycc", "target_lms", "target_offset")},
            "sources": {"direct": direct_sources, "rgb_bound_diagnostic": bound_sources},
            "channels": channels,
        })
    if not results:
        raise ValueError("at least one paired case required")
    return {
        "schema": "yblod.sk4-case-summary.v1", "status": "complete",
        "scope": "SK4 transport code comparison, not perceptual accuracy or Dolby compliance",
        "interpretation": "Negative changes are closer by that metric; positive changes are farther. No production pass threshold.",
        "assumptions": [
            "Each capture's visible-counter/source association is supplied, not independently verified here.",
            "Paired runs use identical reconstruction, RPU, reference capture, rectangle, and colour coordinates.",
            "The bound is an explicit diagnostic, not proof of the SK4's internal implementation.",
            "No fitted offsets or pooled frame scores are applied by this summary.",
            "Output report links and compared tunnel hashes are verified; other diagnostic stages and original captures are not re-read.",
            "CRC validation is inherited from comparisons and covers the first copy of each of two metadata packets.",
        ],
        "implementation_sha256": digest(Path(__file__)),
        "case_count": len(results), "cases": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs=2, action="append", required=True,
                        metavar=("DIRECT_DIR", "BOUND_DIR"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.case)
        save_json(args.output, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"case summary: {error}\n")
    print(json.dumps({"output": str(args.output), "case_count": report["case_count"]}))


if __name__ == "__main__":
    main()
