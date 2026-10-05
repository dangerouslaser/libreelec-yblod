#!/usr/bin/env python3
"""Check saved reconstruction stages and compare preparation policies.

These are reconstructed 4:2:0 component codes, NOT HDMI transport or displayed
RGB. Differences here do not establish accuracy against either Ugoos box.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from extract_frame import digest, save_json
from reference import CHANNELS


def load(directory, record, shape, signed=False):
    path = (directory / record["file"]).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("stage path escapes result directory")
    dtype = "<i4" if signed else "<u2"
    size = int(np.prod(shape))
    if path.stat().st_size != size * np.dtype(dtype).itemsize or digest(path) != record["sha256"]:
        raise ValueError(f"stage integrity failed: {path.name}")
    return np.fromfile(path, dtype=dtype).reshape(shape).astype(np.int64)


def checked_report(directory):
    report = json.loads((directory / "report.json").read_text())
    if report["schema"] != "yblod.composer-result.v1" or report["status"] != "complete":
        raise ValueError("completed composer result required")
    return report


def inspect(directory):
    directory = Path(directory).resolve()
    report = checked_report(directory)
    manifest = report["input_manifest"]
    depth = manifest["metadata"]["output_bit_depth"]
    result = {"result_report_sha256": digest(directory / "report.json"),
              "scope": "reconstruction-stage checks, not rendered-picture accuracy",
              "output_bit_depth": depth, "channels": {}}
    for channel in CHANNELS:
        divisor = 1 if channel == "Y" else 2
        shape = manifest["height"] // divisor, manifest["width"] // divisor
        arrays = {stage: load(directory, report["stages"][f"{stage}_{channel}"], shape,
                              signed=stage in ("residual", "sum"))
                  for stage in ("mapped", "residual", "sum", "reconstructed")}
        if not np.array_equal(arrays["sum"], arrays["mapped"] + arrays["residual"]):
            raise ValueError(f"{channel}: signed addition stage mismatch")
        rounded = (arrays["sum"] + (1 << (15 - depth))) >> (16 - depth)
        expected = np.clip(rounded, 0, (1 << depth) - 1)
        if not np.array_equal(arrays["reconstructed"], expected):
            raise ValueError(f"{channel}: rounding/final-bound stage mismatch")
        result["channels"][channel] = {
            "samples": int(np.prod(shape)), "signed_addition_verified": True,
            "final_rounding_and_bounds_verified": True,
            "rounded_below_zero": int(np.count_nonzero(rounded < 0)),
            "rounded_above_output_maximum": int(np.count_nonzero(rounded >= 1 << depth)),
            "mapped_at_lower_bound": int(np.count_nonzero(arrays["mapped"] == 0)),
            "mapped_at_upper_bound": int(np.count_nonzero(arrays["mapped"] == 65535)),
            "ranges": {k: [int(v.min()), int(v.max())] for k, v in arrays.items()}}
    return result


def stats(a, b):
    delta = b.astype(np.int64) - a.astype(np.int64)
    absolute = np.abs(delta)
    return {"samples": int(delta.size), "identical_percent": float(100 * np.mean(delta == 0)),
            "mean_absolute_codes": float(np.mean(absolute)),
            "maximum_absolute_codes": int(absolute.max()),
            "over_one_code_percent": float(100 * np.mean(absolute > 1)),
            "over_sixteen_codes_percent": float(100 * np.mean(absolute > 16))}


def compare(first, second):
    first, second = Path(first).resolve(), Path(second).resolve()
    a, b = checked_report(first), checked_report(second)
    ma, mb = a["input_manifest"], b["input_manifest"]
    for key in ("width", "height", "format", "transfer", "chroma_location", "metadata"):
        if ma[key] != mb[key]:
            raise ValueError(f"cannot compare different {key}")
    for key in ("source_extraction_sha256", "source_composition_sha256", "source_plane_sha256"):
        if ma["preparation_details"][key] != mb["preparation_details"][key]:
            raise ValueError("different native source inputs")
    result = {"scope": "preparation-policy sensitivity only; not a hardware accuracy score",
              "first_policy": ma["preparation_details"]["policy"],
              "second_policy": mb["preparation_details"]["policy"],
              "first_report_sha256": digest(first / "report.json"),
              "second_report_sha256": digest(second / "report.json"), "channels": {}}
    for channel in CHANNELS:
        divisor = 1 if channel == "Y" else 2
        shape = ma["height"] // divisor, ma["width"] // divisor
        aa = load(first, a["stages"][f"reconstructed_{channel}"], shape)
        bb = load(second, b["stages"][f"reconstructed_{channel}"], shape)
        result["channels"][channel] = stats(aa, bb)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new JSON report file")
    args = parser.parse_args()
    try:
        result = {"first": inspect(args.result)}
        if args.compare:
            result["second"] = inspect(args.compare)
            result["comparison"] = compare(args.result, args.compare)
        save_json(args.output, result)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"inspection: {error}\n")
    print(json.dumps(result, indent=2))
