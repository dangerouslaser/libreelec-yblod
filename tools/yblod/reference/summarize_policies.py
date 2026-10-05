#!/usr/bin/env python3
"""Collect matched five-policy SK4 reports without pooling or choosing a winner.

Each repeated --case takes five output directories in POLICIES order. Each
directory must contain output.json and sk4.json. Input report links and compared
tunnel hashes are checked with bounded streaming, not full-frame image loads.
"""
import argparse
import json
from pathlib import Path

from extract_frame import digest, save_json
from summarize_cases import MATCH_COMPARISON, MATCH_OUTPUT, METRICS, checked


POLICIES = ("direct", "rgb-bound-diagnostic", "rgb-lower-bound-diagnostic",
            "rgb-upper-bound-diagnostic", "source-pq-bound-diagnostic")


def summarize(cases):
    frames, seen = [], set()
    for directories in cases:
        if len(directories) != len(POLICIES):
            raise ValueError("each case requires exactly five policy directories")
        runs = [checked(directory, policy) for directory, policy in zip(directories, POLICIES)]
        baseline, baseline_comparison, _ = runs[0]
        frame_id = baseline["identity"]["frame_id"]
        if frame_id in seen:
            raise ValueError("duplicate frame identity in case list")
        seen.add(frame_id)
        controls = {}
        for policy, (info, comparison, sources) in zip(POLICIES, runs):
            for key in MATCH_OUTPUT:
                if info[key] != baseline[key]:
                    raise ValueError(f"{policy} output mismatch: {key}")
            for key in MATCH_COMPARISON:
                if comparison[key] != baseline_comparison[key]:
                    raise ValueError(f"{policy} comparison mismatch: {key}")
            channels = {}
            for name in ("I", "P", "T"):
                scores = comparison["channels"][name]
                original = baseline_comparison["channels"][name]
                change = {metric: scores[metric] - original[metric] for metric in METRICS}
                channels[name] = {
                    "metrics": dict(scores), "change_vs_direct": change,
                    "metrics_increased": [metric for metric in METRICS if change[metric] > 0],
                }
            controls[policy] = {
                "sources": sources, "channels": channels,
                "byte_identical_to_direct": (info["stages"]["unembedded_tunnel"]["sha256"]
                                             == baseline["stages"]["unembedded_tunnel"]["sha256"]),
            }
        frames.append({
            "identity": baseline["identity"], "identity_basis": baseline_comparison["identity_basis"],
            "active_rectangle": baseline["active_rectangle"],
            "capture_sha256": baseline_comparison["capture_sha256"],
            "identity_file_sha256": baseline_comparison["identity_file_sha256"],
            "composer_report_sha256": baseline["composer_report_sha256"],
            "rpu_sha256": baseline["rpu_sha256"],
            "target_coordinates": {key: baseline[key] for key in ("target_ycc", "target_lms", "target_offset")},
            "controls": controls,
        })
    if not frames:
        raise ValueError("at least one five-policy case required")
    return {
        "schema": "yblod.sk4-policy-summary.v1", "status": "complete",
        "scope": "SK4 transport code comparison; not perceptual accuracy or Dolby compliance",
        "policies": list(POLICIES), "case_count": len(frames), "run_count": len(frames) * len(POLICIES),
        "interpretation": "Negative changes are closer by that metric; positive changes are farther. No pooled score or automatic winner.",
        "assumptions": [
            "All five runs for a frame share reconstruction, RPU, reference capture, active rectangle, and colour coordinates.",
            "Capture visible-counter/source association is supplied, not independently re-established here.",
            "Scores are copied from comparisons, not recomputed. Output-report links and compared-tunnel hashes are verified.",
            "Other diagnostic stages and original captures are not re-read; inherited CRC checks cover the first copy of two metadata packets.",
            "Byte identity compares SHA-256 hashes of complete unembedded packed tunnel files, including inactive borders.",
            "Diagnostic limiting policies do not establish the SK4's internal method. No fitted offsets or production pass threshold.",
        ],
        "implementation_sha256": digest(Path(__file__)), "cases": frames,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs=5, action="append", required=True,
                        metavar=("DIRECT", "RGB_BOUND", "RGB_LOWER", "RGB_UPPER", "SOURCE_PQ_BOUND"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.case)
        save_json(args.output, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"policy summary: {error}\n")
    print(json.dumps({"output": str(args.output), "case_count": report["case_count"],
                      "run_count": report["run_count"]}))


if __name__ == "__main__":
    main()
