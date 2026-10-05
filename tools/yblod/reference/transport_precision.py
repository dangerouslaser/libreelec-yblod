#!/usr/bin/env python3
"""Audit saved tunnel-code precision without changing pixels or fitting offsets.

Separates each signed 12-bit difference into its weighted high-byte difference
and low-nibble difference. Absolute component differences are NOT additive.
Only aggregate histograms/counts are written; processing uses 32-row strips.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

from compare_output import decode_ce, unpack_rgb, matrices
from diagnose_frame import packet_copies, read_strip
from extract_frame import digest, save_json
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET
from summarize_cases import checked

STRIP_ROWS = 32
GROUPS = ("all", "even_row", "odd_row", "even_sample_column", "odd_sample_column",
          "row_even_column_even", "row_even_column_odd", "row_odd_column_even", "row_odd_column_odd")


def new_accumulator():
    result = {key: 0 for key in ("samples", "signed_sum", "absolute_sum", "square_sum", "maximum_absolute_codes",
              "high8_signed_sum", "high8_absolute_sum", "low4_signed_sum", "low4_absolute_sum",
              "low_only_changed", "high_only_changed", "opposite_signed_components", "identical")}
    for side in ("generated", "capture", "xor"):
        result[side + "_low4"] = np.zeros(16, dtype=np.int64)
        result[side + "_high8"] = np.zeros(256, dtype=np.int64)
    result["error_histogram"] = np.zeros(8191, dtype=np.int64)
    return result


def update(result, ours, capture):
    ours, capture = np.asarray(ours), np.asarray(capture)
    if (ours.shape != capture.shape or ours.dtype.kind not in "ui" or capture.dtype.kind not in "ui"
            or np.any((ours < 0) | (ours > 4095)) or np.any((capture < 0) | (capture > 4095))):
        raise ValueError("equal-shaped 12-bit integer code arrays required")
    a, b = ours.astype(np.int64, copy=False).reshape(-1), capture.astype(np.int64, copy=False).reshape(-1)
    delta = a-b
    high = (a >> 4)-(b >> 4)
    low = (a & 15)-(b & 15)
    if not np.array_equal(delta, high*16 + low):
        raise ValueError("signed high/low identity failed")
    result["samples"] += int(a.size)
    for key, value in (("signed_sum", delta.sum()), ("absolute_sum", np.abs(delta).sum()),
                       ("square_sum", (delta*delta).sum()), ("high8_signed_sum", high.sum()),
                       ("high8_absolute_sum", np.abs(high).sum()), ("low4_signed_sum", low.sum()),
                       ("low4_absolute_sum", np.abs(low).sum()), ("low_only_changed", np.count_nonzero((high == 0) & (low != 0))),
                       ("high_only_changed", np.count_nonzero((high != 0) & (low == 0))),
                       ("opposite_signed_components", np.count_nonzero(high*low < 0)), ("identical", np.count_nonzero(delta == 0))):
        result[key] += int(value)
    if delta.size:
        result["maximum_absolute_codes"] = max(result["maximum_absolute_codes"], int(np.abs(delta).max()))
    for side, values in (("generated", a), ("capture", b), ("xor", a ^ b)):
        result[side + "_low4"] += np.bincount(values & 15, minlength=16)
        result[side + "_high8"] += np.bincount(values >> 4, minlength=256)
    result["error_histogram"] += np.bincount(delta + 4095, minlength=8191)


def finish(result):
    n = result["samples"]
    if result["signed_sum"] != 16*result["high8_signed_sum"] + result["low4_signed_sum"]:
        raise ValueError("accumulated signed high/low identity failed")
    if int(result["error_histogram"].sum()) != n:
        raise ValueError("error histogram sample count differs")
    mean = lambda value: value/n if n else None
    values = {}
    for side in ("generated", "capture"):
        low, high = result[side + "_low4"], result[side + "_high8"]
        if int(low.sum()) != n or int(high.sum()) != n:
            raise ValueError("code histogram sample count differs")
        values[side] = {"code_mod16_histogram": low.tolist(),
                        "code_mod4_histogram": [int(low[k::4].sum()) for k in range(4)],
                        "high8_histogram": high.tolist(),
                        "mean_low4_value": mean(int(np.dot(low, np.arange(16)))),
                        "mean_high8_value": mean(int(np.dot(high, np.arange(256))))}
    bits = []
    for bit in range(12):
        suffix, shift, size = ("_low4", bit, 16) if bit < 4 else ("_high8", bit-4, 256)
        selected = (np.arange(size) & (1 << shift)) != 0
        counts = {side: int(result[side + suffix][selected].sum()) for side in ("generated", "capture", "xor")}
        bits.append({"bit": bit, "generated_set": counts["generated"], "capture_set": counts["capture"],
                     "xor_count": counts["xor"], "xor_rate": mean(counts["xor"]),
                     "signed_contribution_sum_codes": (counts["generated"]-counts["capture"])*(1 << bit),
                     "mean_signed_contribution_codes": mean((counts["generated"]-counts["capture"])*(1 << bit))})
    bit_sum = sum(record["signed_contribution_sum_codes"] for record in bits)
    if bit_sum != result["signed_sum"]:
        raise ValueError("per-bit signed contribution identity failed")
    if any(int(result["xor" + suffix].sum()) != n for suffix in ("_low4", "_high8")):
        raise ValueError("XOR histogram sample count differs")
    return {"samples": n, "values": values,
            "signed_decomposition": {"identity_exact": True, "per_bit_identity_exact": True,
                                     "per_bit_signed_sum": bit_sum, "delta12_sum": result["signed_sum"],
                                     "weighted_high8_sum": 16*result["high8_signed_sum"], "low4_sum": result["low4_signed_sum"],
                                     "mean_delta12_codes": mean(result["signed_sum"]),
                                     "mean_weighted_high8_codes": mean(16*result["high8_signed_sum"]),
                                     "mean_high8_units": mean(result["high8_signed_sum"]), "mean_low4_codes": mean(result["low4_signed_sum"])},
            "absolute_errors_not_additive": {"mean_delta12_codes": mean(result["absolute_sum"]),
                                             "mean_weighted_high8_codes": mean(16*result["high8_absolute_sum"]),
                                             "mean_low4_codes": mean(result["low4_absolute_sum"])},
            "rmse_delta12_codes": (result["square_sum"]/n)**.5 if n else None,
            "maximum_absolute_delta12_codes": result["maximum_absolute_codes"] if n else None,
            "events": {key: result[key] for key in ("identical", "low_only_changed", "high_only_changed", "opposite_signed_components")},
            "delta12_histogram_nonzero_bins": [[i-4095, int(count)] for i, count in enumerate(result["error_histogram"]) if count],
            "bit_counts": bits}


def coordinate_masks(rows, sample_columns):
    rows, columns = np.asarray(rows), np.asarray(sample_columns)
    if (rows.ndim != 1 or columns.ndim != 1 or rows.dtype.kind not in "ui" or columns.dtype.kind not in "ui"
            or np.any(rows < 0) or np.any(columns < 0)):
        raise ValueError("one-dimensional integer coordinate arrays required")
    row_even = np.broadcast_to(rows[:, None] % 2 == 0, (len(rows), len(columns)))
    column_even = np.broadcast_to(columns[None, :] % 2 == 0, (len(rows), len(columns)))
    return {"all": np.ones(row_even.shape, bool), "even_row": row_even, "odd_row": ~row_even,
            "even_sample_column": column_even, "odd_sample_column": ~column_even,
            "row_even_column_even": row_even & column_even, "row_even_column_odd": row_even & ~column_even,
            "row_odd_column_even": ~row_even & column_even, "row_odd_column_odd": ~row_even & ~column_even}


def audit(baseline_output, capture):
    baseline_output, capture = Path(baseline_output).resolve(), Path(capture).resolve()
    info, comparison, provenance = checked(baseline_output, "direct")
    for key, expected in (("target_ycc", TARGET_YCC), ("target_lms", TARGET_LMS), ("target_offset", TARGET_OFFSET)):
        if not np.array_equal(info[key], expected):
            raise ValueError("baseline colour coordinates differ")
    if info["transport_sampling"] != "P/T co-sited at even x; top-down RGB8":
        raise ValueError("unsupported baseline packing geometry")
    w, h = info["width"], info["height"]
    l, t, r, b = info["active_rectangle"]
    if w*3 % 8 or t*w + l < 6144:
        raise ValueError("unsupported capture alignment or metadata overlap")
    if capture.stat().st_size != w*h*3 or digest(capture) != comparison["capture_sha256"]:
        raise ValueError("capture integrity mismatch")
    accumulators = {channel: {group: new_accumulator() for group in GROUPS} for channel in ("I", "P", "T")}
    tunnel = baseline_output / info["stages"]["unembedded_tunnel"]["file"]
    with tunnel.open("rb") as generated_stream, capture.open("rb") as captured_stream:
        initial = decode_ce(read_strip(captured_stream, 0, (6144+w-1)//w, w, "u1"))
        metadata = packet_copies(*initial)
        # Packet bytes describe metadata, not a picture; keep only validation
        # results here because this audit publishes aggregate precision data.
        metadata.pop("packet_hex", None)
        if any(not np.array_equal(a, c) for a, c in zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS))):
            raise ValueError("capture colour coordinates differ")
        for start in range(t, b, STRIP_ROWS):
            stop = min(start + STRIP_ROWS, b)
            ours = unpack_rgb(*np.moveaxis(read_strip(generated_stream, start, stop, w, "u1"), -1, 0))
            theirs = decode_ce(read_strip(captured_stream, start, stop, w, "u1"))
            rows = np.arange(start, stop)
            for channel, plane, indices, columns in (
                    ("I", 0, slice(l, r), np.arange(l, r)),
                    ("P", 1, slice(l, r, 2), np.arange(l, r, 2)//2),
                    ("T", 1, slice(l+1, r, 2), np.arange(l, r, 2)//2)):
                a, c = ours[plane][:, indices], theirs[plane][:, indices]
                for group, mask in coordinate_masks(rows, columns).items():
                    update(accumulators[channel][group], a[mask], c[mask])
    finished = {channel: {group: finish(value) for group, value in groups.items()} for channel, groups in accumulators.items()}
    gaps = {}
    for channel, groups in finished.items():
        count = groups["all"]["samples"]
        divisor = 1 if channel == "I" else 2
        if count != (r-l)*(b-t)//divisor:
            raise ValueError("active sample count mismatch")
        for partition in (("even_row", "odd_row"), ("even_sample_column", "odd_sample_column"), GROUPS[5:]):
            if sum(groups[group]["samples"] for group in partition) != count:
                raise ValueError("coordinate groups do not partition active samples")
        even, odd = groups["even_row"]["signed_decomposition"], groups["odd_row"]["signed_decomposition"]
        gaps[channel] = {key: even[key]-odd[key] if even[key] is not None and odd[key] is not None else None
                         for key in ("mean_delta12_codes", "mean_weighted_high8_codes", "mean_low4_codes")}
    helpers = ("compare_output", "diagnose_frame", "dvtunnel", "dvlms", "summarize_cases", "extract_frame", "output_frame")
    return {"schema": "yblod.transport-precision.v1", "status": "complete", "identity": info["identity"],
            "identity_basis": comparison["identity_basis"], "source_provenance": provenance,
            "capture_sha256": comparison["capture_sha256"], "composer_report_sha256": info["composer_report_sha256"],
            "rpu_sha256": info["rpu_sha256"], "active_rectangle": [l, t, r, b], "width": w, "height": h,
            "metadata": metadata, "processing_strip_rows": STRIP_ROWS,
            "group_definitions": {"rows": "Absolute frame-row parity; active-area cropping does not reset it.",
                                  "columns": "I uses global pixel x parity. P and T both use global co-sited chroma-sample index x/2 parity, not packed-pixel parity.",
                                  "direction": "generated direct baseline minus captured SK4; no adjustment",
                                  "signed_identity": "delta12 = 16*((generated>>4)-(capture>>4)) + ((generated&15)-(capture&15))"},
            "channels": finished, "even_minus_odd_signed_mean_gaps": gaps,
            "runtime": {"numpy_version": np.__version__, "python_version": sys.version.split()[0]},
            "implementation": {"filename": Path(__file__).name, "sha256": digest(Path(__file__)), "source": Path(__file__).read_text()},
            "helper_implementations": {name: {"filename": Path(sys.modules[name].__file__).name,
                                               "sha256": digest(Path(sys.modules[name].__file__))} for name in helpers},
            "caveats": ["Signed high/low contributions add exactly. Their absolute errors do not add because carries/borrows can cancel.",
                        "A low-bit pattern can describe rounding, dithering, processing, or capture behavior; it does not establish which device or stage is wrong.",
                        "Both inputs are already quantized transport outputs. This is not a measurement of proprietary internal arithmetic precision.",
                        "No pixel changes, fitted corrections, spatial shifts, rankings, or perceptual accuracy claims.",
                        "Original capture association is inherited from the supplied visible-counter record. Checksums validate metadata bytes, not picture accuracy.",
                        "Only aggregate histograms/counts and implementation source are published; no source picture samples are included."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_output", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(args.baseline_output, args.capture)
        save_json(args.report, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"transport precision: {error}\n")
    print(json.dumps({"report": str(args.report), "identity": report["identity"]}))


if __name__ == "__main__":
    main()
