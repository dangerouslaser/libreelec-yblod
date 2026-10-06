#!/usr/bin/env python3
"""Publish scalar comparison evidence, never private hashes or source pixels."""
import argparse
import json
from pathlib import Path


def scalars(item):
    fields = ("samples", "changed_samples", "maximum_absolute_codes", "mean_absolute_codes", "rmse_codes")
    result = {k: item[k] for k in fields}
    result["mean_signed_codes"] = item["signed_sum"] / item["samples"]
    result["identical_percent"] = 100 * (1 - item["changed_samples"] / item["samples"])
    return result


def sanitize(summary, frame):
    if summary.get("schema") != "yblod.paired-sk4-native-colour-checkpoint.v1" or summary.get("status") != "complete":
        raise ValueError("completed paired comparison required")
    runs = summary["comparisons"]
    if len(runs) != 6:
        raise ValueError("six saved capture comparisons required")
    result = dict(schema="yblod.paired-sk4-native-colour-scalar-results.v1", status="complete", frame=frame,
        scope="same native C colour backend, explicit historical direct policy, integer/FP32 native420 composer effect on saved SK4 transport disagreement",
        coverage="one numbered FEL test frame and six saved capture reads; historical linear preparation, not current live VA/cubic preparation",
        caveats=["Not displayed colour accuracy, HDMI-wire fidelity, Dolby conformance or whole-film qualification.",
                 "Saved counter/source association and metadata CRC/matrices are checked; VDIN DMA synchronization remains unverified.",
                 "No fitted offsets, changed target matrices or hardware-matching correction applied.",
                 "Integer baseline is our own native reference, not original CroqueMr playback."],
        resources={k: summary[k] for k in ("before", "after")},
        composer_transport_delta={label: {c: scalars(v) for c, v in runs[0]["channels"][label].items()}
            for label in ("raw_new_minus_old", "packed_new_minus_old")},
        historical_numpy_vs_native_colour={label: {c: scalars(v) for c, v in values.items()}
            for label, values in summary["historical_colour_backend_check"].items()},
        captures=[])
    for run in runs:
        channels = run["channels"]
        result["captures"].append(dict(label=run["capture_label"],
            integer={c: scalars(v) for c, v in channels["packed_old_minus_sk4"].items()},
            fp32={c: scalars(v) for c, v in channels["packed_new_minus_sk4"].items()},
            fp32_minus_integer={c: {k: channels["packed_new_minus_sk4"][c][k] - channels["packed_old_minus_sk4"][c][k]
                for k in ("mean_absolute_codes", "rmse_codes", "maximum_absolute_codes")} for c in ("I", "P", "T")}))
    result["six_capture_ranges"] = {}
    for route in ("integer", "fp32"):
        result["six_capture_ranges"][route] = {c: {k: [min(r[route][c][k] for r in result["captures"]),
            max(r[route][c][k] for r in result["captures"])] for k in
            ("mean_absolute_codes", "rmse_codes", "maximum_absolute_codes")} for c in ("I", "P", "T")}
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("summary", type=Path)
    p.add_argument("--frame", required=True, type=int)
    a = p.parse_args()
    with a.summary.open() as stream:
        source = json.load(stream)
    print(json.dumps(sanitize(source, a.frame), indent=2, allow_nan=False))
