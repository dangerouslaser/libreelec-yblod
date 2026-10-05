#!/usr/bin/env python3
"""Compare matched direct/bounded SK4 output within four RGB-bound regions.

Region labels come from saved float32 diagnostic RGB, not the renderer's
float64 working values. Exact boundary decisions may differ after rounding.
Only active-picture samples are scored; processing uses 64-row strips.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import numpy as np

from compare_output import decode_ce, unpack_rgb
from extract_frame import digest, save_json
from summarize_cases import MATCH_COMPARISON, MATCH_OUTPUT, checked


REGIONS = ("neither", "negative-only", "above-one-only", "both")
METRICS = ("mean_absolute_codes", "rmse_codes", "maximum_absolute_codes")


def labels(rgb):
    if not np.isfinite(rgb).all():
        raise ValueError("non-finite diagnostic RGB")
    negative = np.any(rgb < 0, axis=-1)
    above = np.any(rgb > 1, axis=-1)
    return negative.astype(np.uint8) + 2 * above.astype(np.uint8)


def scores(total):
    n = total["samples"]
    return {"mean_absolute_codes": total["absolute_sum"] / n if n else None,
            "rmse_codes": (total["square_sum"] / n) ** .5 if n else None,
            "maximum_absolute_codes": total["maximum"] if n else None}


def compare_regions(direct_directory, bound_directory, capture):
    direct_directory, bound_directory, capture = map(
        lambda p: Path(p).resolve(), (direct_directory, bound_directory, capture))
    direct, baseline, direct_sources = checked(direct_directory, "direct")
    bound, candidate, bound_sources = checked(bound_directory, "rgb-bound-diagnostic")
    for key in MATCH_OUTPUT:
        if direct[key] != bound[key]:
            raise ValueError(f"paired output mismatch: {key}")
    for key in MATCH_COMPARISON:
        if baseline[key] != candidate[key]:
            raise ValueError(f"paired comparison mismatch: {key}")
    width, height = direct["width"], direct["height"]
    l, t, r, b = direct["active_rectangle"]
    if width * 3 % 8:
        raise ValueError("capture rows must align to 64-bit native words")
    if t * width + l < 6144:
        raise ValueError("active rectangle overlaps metadata")
    if (capture.stat().st_size != width * height * 3
            or digest(capture) != baseline["capture_sha256"]):
        raise ValueError("reference capture integrity mismatch")
    stage = bound["stages"]["diagnostic_rgb_before_bound"]
    rgb_path = (bound_directory / stage["file"]).resolve()
    if (not rgb_path.is_relative_to(bound_directory) or stage["shape"] != [height, width, 3]
            or rgb_path.suffix != ".f32le" or rgb_path.stat().st_size != width * height * 12
            or digest(rgb_path) != stage["sha256"]):
        raise ValueError("diagnostic RGB integrity mismatch")
    totals = {region: {name: {policy: {"samples": 0, "absolute_sum": 0,
                                      "square_sum": 0, "maximum": 0}
                              for policy in ("direct", "rgb_bound_diagnostic")}
                       for name in ("I", "P", "T")} for region in REGIONS}
    paths = [direct_directory / direct["stages"]["unembedded_tunnel"]["file"],
             bound_directory / bound["stages"]["unembedded_tunnel"]["file"], capture, rgb_path]
    with ExitStack() as stack:
        streams = [stack.enter_context(path.open("rb")) for path in paths]
        for stream, bytes_per_pixel in zip(streams, (3, 3, 3, 12)):
            stream.seek(t * width * bytes_per_pixel)
        for start in range(t, b, 64):
            rows = min(64, b - start)
            arrays = []
            for stream, dtype, bytes_per_pixel in zip(streams, ("u1", "u1", "u1", "<f4"), (3, 3, 3, 12)):
                data = stream.read(rows * width * bytes_per_pixel)
                if len(data) != rows * width * bytes_per_pixel:
                    raise ValueError("truncated input strip")
                arrays.append(np.frombuffer(data, dtype=dtype).reshape(rows, width, 3))
            region_ids = labels(arrays[3][:, l:r])
            generated = [unpack_rgb(*np.moveaxis(array, -1, 0)) for array in arrays[:2]]
            reference = decode_ce(arrays[2])
            for name, indices, mask in (("I", slice(l, r), region_ids),
                                        ("P", slice(l, r, 2), region_ids[:, ::2]),
                                        ("T", slice(l + 1, r, 2), region_ids[:, ::2])):
                plane = 0 if name == "I" else 1
                for policy, current in zip(("direct", "rgb_bound_diagnostic"), generated):
                    delta = np.abs(current[plane][:, indices].astype(np.int64)
                                   - reference[plane][:, indices])
                    for region_id, region in enumerate(REGIONS):
                        values = delta[mask == region_id]
                        total = totals[region][name][policy]
                        total["samples"] += int(values.size)
                        if values.size:
                            total["absolute_sum"] += int(values.sum())
                            total["square_sum"] += int((values * values).sum())
                            total["maximum"] = max(total["maximum"], int(values.max()))
    regions = {}
    for region in REGIONS:
        regions[region] = {}
        for name in ("I", "P", "T"):
            a, c = (totals[region][name][policy] for policy in ("direct", "rgb_bound_diagnostic"))
            if a["samples"] != c["samples"]:
                raise ValueError("paired region sample counts differ")
            first, second = scores(a), scores(c)
            change = {metric: second[metric] - first[metric] if a["samples"] else None
                      for metric in METRICS}
            regions[region][name] = {"samples": a["samples"], "direct": first,
                                      "rgb_bound_diagnostic": second,
                                      "change_bound_minus_direct": change}
    partition = {}
    for name in ("I", "P", "T"):
        expected = (r - l) * (b - t) // (1 if name == "I" else 2)
        actual = sum(regions[region][name]["samples"] for region in REGIONS)
        if actual != expected:
            raise ValueError("regions do not partition active samples")
        partition[name] = actual
    return {
        "schema": "yblod.sk4-region-comparison.v1", "status": "complete",
        "scope": "Transport code errors by diagnostic RGB region, not perceptual accuracy or Dolby compliance",
        "identity": direct["identity"], "identity_basis": baseline["identity_basis"],
        "active_rectangle": direct["active_rectangle"], "capture_sha256": baseline["capture_sha256"],
        "composer_report_sha256": direct["composer_report_sha256"], "rpu_sha256": direct["rpu_sha256"],
        "sources": {"direct": direct_sources, "rgb_bound_diagnostic": bound_sources,
                    "diagnostic_rgb_sha256": stage["sha256"]},
        "target_coordinates": {key: direct[key] for key in ("target_ycc", "target_lms", "target_offset")},
        "region_definition": "Across each saved RGB triple: any component <0, any component >1; equality to 0 or 1 is in range.",
        "chroma_region_sampling": "P and T both use the region of their co-sited even-x RGB triple.",
        "caveats": [
            "Region labels use saved float32 diagnostics; computation used float64, so boundary classifications may differ.",
            "Capture identity and first-copy metadata CRC checks are inherited from existing comparisons; capture bytes are hash-verified here.",
            "Negative changes mean closer by that metric, not proof of the SK4's internal limiting method.",
            "Empty regions have zero samples and null metrics; no production pass threshold or fitted offsets.",
        ],
        "processing_strip_rows": 64, "partition_sample_counts": partition,
        "implementation_sha256": digest(Path(__file__)), "regions": regions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direct_directory", type=Path)
    parser.add_argument("bound_directory", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_regions(args.direct_directory, args.bound_directory, args.capture)
        save_json(args.output, result)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"region comparison: {error}\n")
    print(json.dumps({"output": str(args.output), "identity": result["identity"]}))


if __name__ == "__main__":
    main()
