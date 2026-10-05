#!/usr/bin/env python3
"""Back-project co-sited SK4 samples through signalled colour coordinates.

This is a diagnostic coordinate change, not recovery of proprietary internal
buffers. Invalid inverse domains and forward clipping cases are excluded rather
than clipped. The generated tunnel supplies a quantized round-trip control.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import numpy as np

from compare_output import decode_ce, unpack_rgb, matrices
from diagnose_frame import packet_copies, read_strip
from extract_frame import digest, save_json
from output_frame import (TARGET_YCC, TARGET_LMS, TARGET_OFFSET, expand_left,
                          matrix, pq_decode, pq_encode, provenance, source_matrices)
from summarize_cases import checked

STRIP_ROWS = 32


def in_unit_domain(values):
    return np.all(np.isfinite(values) & (values >= 0) & (values <= 1), axis=-1)


def inverse_codes(codes, dm):
    codes = np.asarray(codes, dtype=float)
    if codes.ndim != 3 or codes.shape[-1] != 3 or not np.isfinite(codes).all() or np.any((codes < 0) | (codes > 4095)):
        raise ValueError("finite 12-bit transport triples required")
    source_ycc, source_offset, source_lms = source_matrices(dm)
    target_nonlinear = matrix(TARGET_YCC, codes / 4096 - TARGET_OFFSET)
    first = in_unit_domain(target_nonlinear)
    # Invalid entries get safe placeholders for arithmetic only. Their results
    # become NaN and cannot enter measurements; this is not a limiting policy.
    safe_target = np.where(first[..., None], target_nonlinear, 0.)
    common = matrix(TARGET_LMS, pq_decode(safe_target))
    source_linear = matrix(np.linalg.inv(source_lms), common)
    second = in_unit_domain(source_linear)
    valid = first & second
    safe_source = np.where(valid[..., None], source_linear, 0.)
    reconstructed = (matrix(np.linalg.inv(source_ycc), pq_encode(safe_source)) + source_offset) * 4096
    reconstructed[~valid] = np.nan
    return reconstructed, valid, {
        "target_nonlinear_outside_unit_domain": int(np.count_nonzero(~first)),
        "source_linear_outside_unit_domain_after_valid_target": int(np.count_nonzero(first & ~second)),
        "valid_inverse_source_codes_outside_storage_range": int(np.count_nonzero(valid & np.any((reconstructed < 0) | (reconstructed > 4095), axis=-1))),
        "valid": int(np.count_nonzero(valid))}


def co_sited(intensity, chroma, left, right):
    if left % 2 or right % 2:
        raise ValueError("even horizontal bounds required")
    return np.stack([intensity[:, left:right:2], chroma[:, left:right:2],
                     chroma[:, left+1:right:2]], axis=-1)


def total():
    return {"samples": 0, "signed_sum": 0., "absolute_sum": 0., "square_sum": 0., "max_absolute": 0.}


def add(result, values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("non-finite value reached measurement")
    result["samples"] += int(values.size)
    result["signed_sum"] += float(values.sum())
    result["absolute_sum"] += float(np.abs(values).sum())
    result["square_sum"] += float((values * values).sum())
    if values.size:
        result["max_absolute"] = max(result["max_absolute"], float(np.abs(values).max()))


def finish(result):
    n = result["samples"]
    return {"samples": n, "mean_signed_codes": result["signed_sum"] / n if n else None,
            "mean_absolute_codes": result["absolute_sum"] / n if n else None,
            "rmse_codes": (result["square_sum"] / n) ** .5 if n else None,
            "maximum_absolute_codes": result["max_absolute"] if n else None}


def checked_map(directory, record, shape, dtype):
    directory = Path(directory).resolve()
    path = (directory / record["file"]).resolve()
    if (not path.is_relative_to(directory) or path.stat().st_size != int(np.prod(shape)) * np.dtype(dtype).itemsize
            or digest(path) != record["sha256"]):
        raise ValueError("reconstruction stage integrity mismatch")
    return np.memmap(path, dtype=dtype, mode="r", shape=shape)


def diagnose(output, result, extraction, capture):
    output, result, extraction, capture = [Path(p).resolve() for p in (output, result, extraction, capture)]
    info, comparison, hashes = checked(output, "direct")
    if any(not np.array_equal(info[key], value) for key, value in
           (("target_ycc", TARGET_YCC), ("target_lms", TARGET_LMS), ("target_offset", TARGET_OFFSET))):
        raise ValueError("generated colour coordinates differ")
    composer, dm, identity = provenance(result, extraction)
    if (digest(result / "report.json") != info["composer_report_sha256"] or dm != info["source_dm"]
            or digest(extraction / "rpu.json") != info["rpu_sha256"] or identity != info["identity"]):
        raise ValueError("source-frame provenance mismatch")
    h, w = info["height"], info["width"]
    l, t, r, b = info["active_rectangle"]
    if (composer["input_manifest"]["height"], composer["input_manifest"]["width"]) != (h, w):
        raise ValueError("composer/output geometry mismatch")
    if w * 3 % 8 or t * w + l < 6144 or capture.stat().st_size != w * h * 3 or digest(capture) != comparison["capture_sha256"]:
        raise ValueError("capture integrity or layout mismatch")
    if info["chroma_expansion"] != "bilinear-left-edge-replicated-float64":
        raise ValueError("unsupported reconstruction chroma expansion")
    planes = [checked_map(result, composer["stages"]["reconstructed_" + name],
                          (h, w) if name == "Y" else (h//2, w//2), "<u2") for name in ("Y", "Cb", "Cr")]
    mapped = checked_map(result, composer["stages"]["mapped_Y"], (h, w), "<u2")
    residual = checked_map(result, composer["stages"]["residual_Y"], (h, w), "<i4")
    source_ycc, source_offset, source_lms = source_matrices(dm)
    inverse_target_lms = np.linalg.inv(TARGET_LMS)
    names = ("capture_minus_composer", "generated_roundtrip_minus_composer", "capture_minus_generated_roundtrip")
    scores = {name: {channel: {group: total() for group in ("all", "even_row", "odd_row")}
                     for channel in ("Y", "Cb", "Cr")} for name in names}
    hypotheses = {name: total() for name in ("capture_minus_full_enhancement_Y", "capture_minus_zero_enhancement_Y",
                                           "expected_enhancement_Y", "capture_implied_enhancement_Y")}
    exclusions = {name: 0 for name in ("samples", "source_forward_domain_or_target_boundary", "capture_transport_boundary", "capture_inverse_domain",
                                      "generated_inverse_domain", "union_excluded", "valid")}
    inverse_counts = {name: {} for name in ("capture", "generated")}
    with ExitStack() as stack:
        generated_stream, captured_stream = [stack.enter_context(p.open("rb")) for p in
            (output / info["stages"]["unembedded_tunnel"]["file"], capture)]
        initial = decode_ce(read_strip(captured_stream, 0, (6144+w-1)//w, w, "u1"))
        metadata = packet_copies(*initial)
        if any(not np.array_equal(a, c) for a, c in zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS))):
            raise ValueError("capture colour coordinates differ")
        for start in range(t, b, STRIP_ROWS):
            stop = min(b, start + STRIP_ROWS)
            generated_codes = co_sited(*unpack_rgb(*np.moveaxis(read_strip(generated_stream, start, stop, w, "u1"), -1, 0)), l, r)
            captured_codes = co_sited(*decode_ce(read_strip(captured_stream, start, stop, w, "u1")), l, r)
            ours, ours_valid, ours_counts = inverse_codes(generated_codes, dm)
            theirs, theirs_valid, theirs_counts = inverse_codes(captured_codes, dm)
            for name, counts in (("capture", theirs_counts), ("generated", ours_counts)):
                for key, value in counts.items():
                    inverse_counts[name][key] = inverse_counts[name].get(key, 0) + value
            expected = np.stack([planes[0][start:stop, l:r:2],
                                 expand_left(planes[1], start, stop)[:, l:r:2],
                                 expand_left(planes[2], start, stop)[:, l:r:2]], axis=-1)
            if np.any((expected < 0) | (expected > 4095)):
                raise ValueError("reconstructed plane outside 12-bit range")
            nonlinear = matrix(source_ycc, expected / 4096 - source_offset)
            forward = in_unit_domain(nonlinear)
            target_linear = matrix(inverse_target_lms, matrix(source_lms, pq_decode(np.where(forward[..., None], nonlinear, 0.))))
            # Saturated generated codewords cannot determine the pre-bound value.
            forward &= in_unit_domain(target_linear) & np.all((generated_codes > 0) & (generated_codes < 4095), axis=-1)
            captured_interior = np.all((captured_codes > 0) & (captured_codes < 4095), axis=-1)
            valid = forward & ours_valid & theirs_valid & captured_interior
            for name, count in (("samples", valid.size), ("source_forward_domain_or_target_boundary", np.count_nonzero(~forward)),
                                ("capture_transport_boundary", np.count_nonzero(~captured_interior)),
                                ("capture_inverse_domain", np.count_nonzero(~theirs_valid)), ("generated_inverse_domain", np.count_nonzero(~ours_valid)),
                                ("union_excluded", np.count_nonzero(~valid)), ("valid", np.count_nonzero(valid))):
                exclusions[name] += int(count)
            rows = np.arange(start, stop)[:, None]
            for name, delta in zip(names, (theirs-expected, ours-expected, theirs-ours)):
                for i, channel in enumerate(("Y", "Cb", "Cr")):
                    for group, mask in (("all", valid), ("even_row", valid & (rows % 2 == 0)), ("odd_row", valid & (rows % 2 == 1))):
                        add(scores[name][channel][group], delta[..., i][mask])
            mapped_y = mapped[start:stop, l:r:2].astype(np.int64)
            residual_y = residual[start:stop, l:r:2].astype(np.int64)
            if not np.array_equal(np.clip((mapped_y + residual_y + 8) >> 4, 0, 4095), expected[..., 0]):
                raise ValueError("saved Y composition arithmetic mismatch")
            zero_el = np.clip((mapped_y + 8) >> 4, 0, 4095)
            for name, values in (("capture_minus_full_enhancement_Y", theirs[..., 0]-expected[..., 0]),
                                 ("capture_minus_zero_enhancement_Y", theirs[..., 0]-zero_el),
                                 ("expected_enhancement_Y", expected[..., 0]-zero_el),
                                 ("capture_implied_enhancement_Y", theirs[..., 0]-zero_el)):
                add(hypotheses[name], values[valid])
    return {"schema": "yblod.inverse-stage-diagnosis.v1", "status": "complete", "identity": identity,
            "provenance": hashes, "composer_report_sha256": info["composer_report_sha256"],
            "rpu_sha256": info["rpu_sha256"], "capture_sha256": comparison["capture_sha256"],
            "metadata": metadata, "source_dm": dm, "active_rectangle": [l, t, r, b],
            "processing_strip_rows": STRIP_ROWS, "sample_grid": "even x only; I,P,T are co-sited, no capture interpolation",
            "exclusions": exclusions, "inverse_domain_counts": inverse_counts,
            "comparisons": {name: {channel: {group: finish(value) for group, value in groups.items()}
                                    for channel, groups in channels.items()} for name, channels in scores.items()},
            "Y_enhancement_hypotheses": {name: finish(value) for name, value in hypotheses.items()},
            "caveats": ["Back-projected source coordinates are inferred, not observed internal SK4 buffers.",
                        "Generated quantized round-trip is a control, not a rigorous bound on capture quantization error; sensitivity depends on local colour.",
                        "Finite inverse source codes outside 0..4095 are reported and retained: they may indicate quantization or a model mismatch, not observed illegal decoder output.",
                        "Exclusions are strict and shared across all comparisons; exclusion category counts overlap.",
                        "Captured or generated transport endpoints 0 and 4095 are conservatively excluded because the unclipped value cannot be recovered.",
                        "A mismatch here does not by itself prove a reconstruction bug: different colour processing, capture association, or irreversible hardware operations can also produce it.",
                        "Zero-enhancement Y is a diagnostic counterfactual, not a permitted playback fallback and not a fitted residual gain.",
                        "Source-frame association is hash-verified; capture identity remains the supplied visible-counter association.",
                        "All valid samples contribute to the main result; parity groups do not change coordinates or fit offsets."],
            "implementation_sha256": digest(Path(__file__))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "result", "extraction", "capture"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = diagnose(args.output, args.result, args.extraction, args.capture)
        save_json(args.report, report)
    except (OSError, KeyError, TypeError, ValueError, np.linalg.LinAlgError) as error:
        parser.exit(1, f"inverse stage: {error}\n")
    print(json.dumps({"report": str(args.report), "valid": report["exclusions"]["valid"]}))


if __name__ == "__main__":
    main()
