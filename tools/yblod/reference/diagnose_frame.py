#!/usr/bin/env python3
"""Locate an existing SK4 discrepancy without fitting or changing image values.

Uses 32-row strips plus a one-row halo. Reports signed errors, fixed spatial
tiles, and errors in smooth/edge and source-domain groups. Group membership is
descriptive, not an acceptance threshold or evidence of a hardware algorithm.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import numpy as np

from compare_output import decode_ce, unpack_rgb, crc32_mpeg2, matrices
from extract_frame import digest, save_json
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET
from summarize_cases import checked

STRIP_ROWS = 32


def packet_copies(intensity, chroma):
    """Require all three embedded copies of each of the two known packets."""
    intensity, chroma = intensity.reshape(-1), chroma.reshape(-1)
    if len(intensity) < 6144 or len(chroma) < 6144:
        raise ValueError("insufficient metadata samples")
    packets = []
    for number in range(2):
        copies = []
        for copy in range(3):
            start = number * 3072 + copy * 1024
            y, c = intensity[start:start + 1024], chroma[start:start + 1024]
            parity = np.array([(int(a).bit_count() + (int(b) >> 1).bit_count()) & 1
                               for a, b in zip(y, c)], dtype=np.uint8)
            payload = np.packbits((c & 1).astype(np.uint8) ^ parity).tobytes()
            if crc32_mpeg2(payload):
                raise ValueError(f"metadata CRC failure packet {number} copy {copy}")
            copies.append(payload)
        if copies[1:] != copies[:1] * 2:
            raise ValueError("metadata copies differ")
        packets.append(copies[0])
    if [p[0] >> 6 for p in packets] != [1, 3]:
        raise ValueError("unsupported metadata packet layout")
    return {"packets": 2, "copies_per_packet": 3, "all_crc_valid": True,
            "copies_identical": True, "packet_hex": [p.hex() for p in packets]}


def new_total():
    return {"samples": 0, "signed_sum": 0, "absolute_sum": 0, "square_sum": 0,
            "negative": 0, "zero": 0, "positive": 0, "maximum_absolute_codes": 0}


def accumulate(total, delta):
    delta = np.asarray(delta, dtype=np.int64)
    total["samples"] += int(delta.size)
    total["signed_sum"] += int(delta.sum())
    total["absolute_sum"] += int(np.abs(delta).sum())
    total["square_sum"] += int((delta * delta).sum())
    for name, condition in (("negative", delta < 0), ("zero", delta == 0), ("positive", delta > 0)):
        total[name] += int(np.count_nonzero(condition))
    if delta.size:
        total["maximum_absolute_codes"] = max(total["maximum_absolute_codes"], int(np.abs(delta).max()))


def finish(total):
    n = total["samples"]
    return {key: value for key, value in total.items() if not key.endswith("_sum")} | {
        "mean_signed_codes": total["signed_sum"] / n if n else None,
        "mean_absolute_codes": total["absolute_sum"] / n if n else None,
        "rmse_codes": (total["square_sum"] / n) ** .5 if n else None}


def gradient(values):
    """Maximum absolute difference from four neighbours, in this channel's grid."""
    values = np.asarray(values, dtype=np.int32)
    result = np.zeros_like(values)
    for axis in (0, 1):
        difference = np.abs(np.diff(values, axis=axis))
        lower = [slice(None), slice(None)]
        upper = lower.copy()
        lower[axis], upper[axis] = slice(1, None), slice(None, -1)
        np.maximum(result[tuple(lower)], difference, out=result[tuple(lower)])
        np.maximum(result[tuple(upper)], difference, out=result[tuple(upper)])
    return result


def read_strip(stream, start, stop, width, dtype):
    itemsize = np.dtype(dtype).itemsize
    stream.seek(start * width * 3 * itemsize)
    data = stream.read((stop - start) * width * 3 * itemsize)
    if len(data) != (stop - start) * width * 3 * itemsize:
        raise ValueError("truncated strip")
    return np.frombuffer(data, dtype=dtype).reshape(stop - start, width, 3)


def diagnose(output, capture):
    output, capture = Path(output).resolve(), Path(capture).resolve()
    raw_info = json.loads((output / "output.json").read_text())
    info, comparison, provenance = checked(output, raw_info["policy"])
    w, h = info["width"], info["height"]
    l, t, r, b = info["active_rectangle"]
    if w * 3 % 8 or t * w + l < 6144:
        raise ValueError("unsupported capture alignment or metadata overlap")
    if capture.stat().st_size != w * h * 3 or digest(capture) != comparison["capture_sha256"]:
        raise ValueError("capture integrity mismatch")
    nonlinear = info["stages"]["source_nonlinear"]
    stage = (output / nonlinear["file"]).resolve()
    if (not stage.is_relative_to(output) or nonlinear["shape"] != [h, w, 3]
            or stage.stat().st_size != w * h * 12 or digest(stage) != nonlinear["sha256"]):
        raise ValueError("source nonlinear stage integrity mismatch")
    totals, histograms, worst = {}, {}, {}
    for name in ("I", "P", "T"):
        totals[name] = {key: new_total() for key in
                       ("all", "smooth_le_4", "intermediate_5_16", "edge_gt_16",
                        "source_in_range", "source_outside", "even_row", "odd_row")}
        totals[name].update({f"tile_{y}_{x}": new_total() for y in range(4) for x in range(8)})
        histograms[name] = np.zeros(8191, dtype=np.int64)
        worst[name] = None
    paths = (output / info["stages"]["unembedded_tunnel"]["file"], capture, stage)
    with ExitStack() as stack:
        ours, theirs, source = [stack.enter_context(path.open("rb")) for path in paths]
        initial = decode_ce(read_strip(theirs, 0, (6144 + w - 1) // w, w, "u1"))
        metadata = packet_copies(*initial)
        if any(not np.array_equal(actual, wanted) for actual, wanted in
               zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS))):
            raise ValueError("capture coordinate matrices differ")
        for start in range(t, b, STRIP_ROWS):
            stop = min(b, start + STRIP_ROWS)
            lo, hi = max(t, start - 1), min(b, stop + 1)
            local = slice(start - lo, stop - lo)
            generated = unpack_rgb(*np.moveaxis(read_strip(ours, start, stop, w, "u1"), -1, 0))
            reference = decode_ce(read_strip(theirs, lo, hi, w, "u1"))
            nl = read_strip(source, start, stop, w, "<f4")
            if not np.isfinite(nl).all():
                raise ValueError("non-finite source nonlinear stage")
            outside = np.any((nl < 0) | (nl > 1), axis=-1)
            rows = np.arange(start, stop)[:, None]
            for name, plane, indices, coordinates in (
                    ("I", 0, slice(l, r), np.arange(l, r)),
                    ("P", 1, slice(l, r, 2), np.arange(l, r, 2)),
                    ("T", 1, slice(l + 1, r, 2), np.arange(l, r, 2))):
                a = generated[plane][:, indices].astype(np.int32)
                c_halo = reference[plane][:, indices]
                c = c_halo[local].astype(np.int32)
                delta = a - c
                g = gradient(c_halo)[local]
                domain = outside[:, l:r] if name == "I" else outside[:, l:r:2]
                masks = {"all": np.ones(delta.shape, bool), "smooth_le_4": g <= 4,
                         "intermediate_5_16": (g > 4) & (g <= 16), "edge_gt_16": g > 16,
                         "source_in_range": ~domain, "source_outside": domain,
                         "even_row": np.broadcast_to(rows % 2 == 0, delta.shape),
                         "odd_row": np.broadcast_to(rows % 2 == 1, delta.shape)}
                ty = np.minimum((rows - t) * 4 // (b - t), 3)
                tx = np.minimum((coordinates - l) * 8 // (r - l), 7)
                for y in range(4):
                    for x in range(8):
                        masks[f"tile_{y}_{x}"] = (ty == y) & (tx == x)
                for key, mask in masks.items():
                    accumulate(totals[name][key], delta[mask])
                histograms[name] += np.bincount(delta.reshape(-1) + 4095, minlength=8191)
                index = np.unravel_index(np.abs(delta).argmax(), delta.shape)
                signed = int(delta[index])
                if worst[name] is None or abs(signed) > abs(worst[name]["signed_codes"]):
                    worst[name] = {"x": int(coordinates[index[1]]), "y": start + int(index[0]),
                                   "signed_codes": signed, "generated": int(a[index]), "capture": int(c[index])}
    results = {}
    for name in totals:
        count = totals[name]["all"]["samples"]
        absolute_histogram = histograms[name][4095:].copy()
        absolute_histogram[1:] += histograms[name][:4095][::-1]
        percentile = int(np.searchsorted(absolute_histogram.cumsum(), (99 * count + 99) // 100))
        results[name] = {"groups": {key: finish(value) for key, value in totals[name].items()},
                         "signed_histogram_nonzero_bins": [[i - 4095, int(v)] for i, v in enumerate(histograms[name]) if v],
                         "p99_absolute_codes_nearest_rank": percentile, "worst_sample": worst[name]}
    return {"schema": "yblod.frame-diagnosis.v1", "status": "complete", "identity": info["identity"],
            "policy": info["policy"], "provenance": provenance, "capture_sha256": digest(capture),
            "source_nonlinear_sha256": nonlinear["sha256"], "metadata": metadata,
            "active_rectangle": [l, t, r, b], "processing_strip_rows": STRIP_ROWS,
            "direction": "generated minus capture, no fitted correction or alignment",
            "group_definitions": {"gradient": "Four-neighbour maximum on the capture channel grid; active-area edge replicated, strip halos retained.",
                                  "tiles": "Fixed 8 columns by 4 rows covering the active rectangle.",
                                  "source_domain": "Any saved source nonlinear RGB component outside [0,1]; float32 diagnostic, not float64 decision.",
                                  "chroma_coordinates": "P and T sample locations both reported at co-sited even x."},
            "caveats": ["Frame association is inherited from the supplied visible-counter record, not independently timestamp-verified.",
                        "No perceptual accuracy score, compliance result, or determination of the proprietary algorithm.",
                        "Smooth-region error can implicate arithmetic/metadata but does not exclude a slowly varying alignment error.",
                        "Edge-region error alone does not distinguish chroma phase, scaling kernel, temporal mismatch, or nonlinear ordering."],
            "implementation_sha256": digest(Path(__file__)), "channels": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = diagnose(args.output_directory, args.capture)
        save_json(args.report, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"frame diagnosis: {error}\n")
    print(json.dumps({"report": str(args.report), "identity": report["identity"]}))


if __name__ == "__main__":
    main()
