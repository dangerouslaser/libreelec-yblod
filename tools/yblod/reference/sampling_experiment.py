#!/usr/bin/env python3
"""Forward-only final chroma expansion experiment; no image fitting or tuning.

The linear-left candidate must reproduce every byte of an existing direct
tunnel. Other variants change only vertical source-chroma expansion. Reports
contain fixed-mask output errors and causal variant-minus-baseline changes;
no images or float stages are saved. Processing uses 32-row strips.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys

import numpy as np

import chroma_geometry
import output_frame
from compare_output import decode_ce, unpack_rgb, matrices
from diagnose_frame import accumulate, finish, gradient, new_total, packet_copies, read_strip
from extract_frame import digest, save_json
from inverse_stage import checked_map
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET, convert, pack, provenance
from summarize_cases import checked

STRIP_ROWS = 32
GROUPS = ("all", "even_row", "odd_row", "smooth_le_4", "intermediate_5_16", "edge_gt_16")
CHANNELS = ("I", "P", "T")
BASELINE = "linear-left"


def active_rectangle(dm, width, height):
    blocks = [b["Level5"] for b in dm["cmv29_metadata"]["ext_metadata_blocks"] if "Level5" in b]
    if len(blocks) != 1:
        raise ValueError("exactly one source active-area block required")
    left, right, top, bottom = [blocks[0][f"active_area_{side}_offset"] for side in ("left", "right", "top", "bottom")]
    return [left, top, width-right, height-bottom]


def produce(planes, dm, variant, start, stop, rectangle):
    l, t, r, b = rectangle
    expected = np.stack([planes[0][start:stop],
                         chroma_geometry.expand(planes[1], start=start, stop=stop, variant=variant),
                         chroma_geometry.expand(planes[2], start=start, stop=stop, variant=variant)], axis=-1)
    # Cubic interpolation can overshoot nominal source codes. Do not silently
    # add a new clamp: the existing direct converter receives those values.
    codes = convert(expected, dm, "direct", lambda *_: None)
    rows = np.arange(start, stop)
    codes[(rows < t) | (rows >= b)] = [0, 2048, 2048]
    codes[:, :l] = codes[:, r:] = [0, 2048, 2048]
    return pack(codes)


def source_text(module):
    path = Path(module.__file__).resolve()
    return {"filename": path.name, "sha256": digest(path), "source": path.read_text()}


def produce_checked(planes, dm, variant, start, stop, rectangle):
    try:
        return produce(planes, dm, variant, start, stop, rectangle)
    except (ValueError, np.linalg.LinAlgError) as error:
        raise ValueError(f"variant {variant}, rows [{start}, {stop}): {error}") from error


def experiment(baseline_output, result, extraction, capture):
    baseline_output, result, extraction, capture = [Path(p).resolve() for p in (baseline_output, result, extraction, capture)]
    info, old_comparison, hashes = checked(baseline_output, "direct")
    if info["chroma_expansion"] != "bilinear-left-edge-replicated-float64":
        raise ValueError("saved baseline does not declare the supported linear-left expansion")
    for key, expected in (("target_ycc", TARGET_YCC), ("target_lms", TARGET_LMS), ("target_offset", TARGET_OFFSET)):
        if not np.array_equal(info[key], expected):
            raise ValueError("baseline colour coordinates differ")
    report, dm, identity = provenance(result, extraction)
    if (identity != info["identity"] or dm != info["source_dm"] or digest(result / "report.json") != info["composer_report_sha256"]
            or digest(extraction / "rpu.json") != info["rpu_sha256"]):
        raise ValueError("source-frame provenance mismatch")
    w, h = info["width"], info["height"]
    if (report["input_manifest"]["width"], report["input_manifest"]["height"]) != (w, h):
        raise ValueError("baseline/composer dimensions differ")
    rectangle = active_rectangle(dm, w, h)
    if rectangle != info["active_rectangle"]:
        raise ValueError("source/baseline active rectangles differ")
    l, t, r, b = rectangle
    if w * 3 % 8 or t*w + l < 6144:
        raise ValueError("unsupported capture alignment or active metadata overlap")
    if capture.stat().st_size != w*h*3 or digest(capture) != old_comparison["capture_sha256"]:
        raise ValueError("capture integrity mismatch")
    planes = [checked_map(result, report["stages"]["reconstructed_" + name],
                          (h, w) if name == "Y" else (h//2, w//2), "<u2") for name in ("Y", "Cb", "Cr")]
    # Read-only maps keep resident input storage modest; range checks themselves
    # are striped and do not allocate a full-frame boolean temporary.
    for plane in planes:
        for start in range(0, plane.shape[0], STRIP_ROWS):
            if np.any(plane[start:start+STRIP_ROWS] > 4095):
                raise ValueError("reconstructed source exceeds 12-bit storage range")
    variants = tuple(chroma_geometry.VARIANTS)
    if BASELINE not in variants or len(variants) != len(set(variants)):
        raise ValueError("invalid experiment variant list")
    scores = {variant: {comparison: {channel: {group: new_total() for group in GROUPS} for channel in CHANNELS}
                        for comparison in ("versus_capture", "minus_baseline")} for variant in variants}
    configurations = {variant: chroma_geometry.configuration(variant) for variant in variants}
    baseline_bytes = 0
    tunnel = baseline_output / info["stages"]["unembedded_tunnel"]["file"]
    with ExitStack() as stack:
        baseline_stream, captured_stream = [stack.enter_context(path.open("rb")) for path in (tunnel, capture)]
        initial = decode_ce(read_strip(captured_stream, 0, (6144+w-1)//w, w, "u1"))
        metadata = packet_copies(*initial)
        if any(not np.array_equal(a, c) for a, c in zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS))):
            raise ValueError("capture colour coordinates differ")
        for start in range(0, h, STRIP_ROWS):
            stop = min(h, start + STRIP_ROWS)
            baseline = produce_checked(planes, dm, BASELINE, start, stop, rectangle)
            saved = read_strip(baseline_stream, start, stop, w, "u1")
            if not np.array_equal(baseline, saved):
                raise ValueError(f"baseline byte mismatch in rows [{start}, {stop}); refusing experiment")
            baseline_bytes += int(saved.nbytes)
            active_start, active_stop = max(start, t), min(stop, b)
            if active_start >= active_stop:
                continue
            active = slice(active_start-start, active_stop-start)
            halo_start, halo_stop = max(t, active_start-1), min(b, active_stop+1)
            halo_local = slice(active_start-halo_start, active_stop-halo_start)
            reference = decode_ce(read_strip(captured_stream, halo_start, halo_stop, w, "u1"))
            baseline_codes = unpack_rgb(*np.moveaxis(baseline[active], -1, 0))
            row_indices = np.arange(active_start, active_stop)[:, None]
            channels = {}
            for name, plane, x_slice in (("I", 0, slice(l, r)), ("P", 1, slice(l, r, 2)), ("T", 1, slice(l+1, r, 2))):
                reference_halo = reference[plane][:, x_slice]
                reference_codes = reference_halo[halo_local].astype(np.int64)
                edge = gradient(reference_halo)[halo_local]
                masks = {"all": np.ones(reference_codes.shape, bool),
                         "even_row": np.broadcast_to(row_indices % 2 == 0, reference_codes.shape),
                         "odd_row": np.broadcast_to(row_indices % 2 == 1, reference_codes.shape),
                         "smooth_le_4": edge <= 4, "intermediate_5_16": (edge > 4) & (edge <= 16),
                         "edge_gt_16": edge > 16}
                channels[name] = (plane, x_slice, reference_codes, baseline_codes[plane][:, x_slice].astype(np.int64), masks)
            for variant in variants:
                candidate = baseline if variant == BASELINE else produce_checked(planes, dm, variant, start, stop, rectangle)
                current = unpack_rgb(*np.moveaxis(candidate[active], -1, 0))
                for name, (plane, x_slice, ref, base, masks) in channels.items():
                    values = current[plane][:, x_slice].astype(np.int64)
                    for comparison, delta in (("versus_capture", values-ref), ("minus_baseline", values-base)):
                        for group, mask in masks.items():
                            accumulate(scores[variant][comparison][name][group], delta[mask])
    if baseline_bytes != w*h*3:
        raise ValueError("incomplete baseline byte verification")
    finished = {variant: {comparison: {channel: {group: finish(value) for group, value in groups.items()}
                                                    for channel, groups in channels.items()}
                          for comparison, channels in comparisons.items()} for variant, comparisons in scores.items()}
    for variant in variants:
        for channel, divisor in (("I", 1), ("P", 2), ("T", 2)):
            expected_count = (r-l)*(b-t)//divisor
            for comparison in ("versus_capture", "minus_baseline"):
                groups = finished[variant][comparison][channel]
                if (groups["all"]["samples"] != expected_count or
                    sum(groups[key]["samples"] for key in ("even_row", "odd_row")) != expected_count or
                    sum(groups[key]["samples"] for key in ("smooth_le_4", "intermediate_5_16", "edge_gt_16")) != expected_count):
                    raise ValueError("comparison masks do not partition the active sample grid")
    return {"schema": "yblod.forward-sampling-experiment.v1", "status": "complete", "identity": identity,
            "source_provenance": hashes, "composer_report_sha256": info["composer_report_sha256"],
            "rpu_sha256": info["rpu_sha256"], "capture_sha256": old_comparison["capture_sha256"],
            "identity_basis": old_comparison["identity_basis"], "source_dm": dm, "width": w, "height": h,
            "active_rectangle": rectangle, "metadata": metadata, "processing_strip_rows": STRIP_ROWS,
            "baseline": {"variant": BASELINE, "byte_identical": True, "verified_bytes": baseline_bytes,
                         "tunnel_sha256": info["stages"]["unembedded_tunnel"]["sha256"]},
            "held_fixed": {"policy": "direct", "horizontal_expansion": "baseline bilinear left-co-sited",
                           "target_ycc": TARGET_YCC.tolist(), "target_lms": TARGET_LMS.tolist(),
                           "target_offset": TARGET_OFFSET.tolist(), "quantization": info["quantization"],
                           "transport_sampling": info["transport_sampling"]},
            "group_definitions": {"gradient": "Four-neighbour maximum from the same captured channel; P/T use their half-width grids. One-row strip halos; active-area boundaries replicated.",
                                  "rows": "Absolute frame-row parity, not active-area-relative parity.",
                                  "chroma": "Both P and T are co-sited at even x; T is stored in the neighbouring packed pixel.",
                                  "direction": "versus_capture: candidate minus SK4; minus_baseline: candidate minus unchanged linear-left."},
            "variants": {variant: {"configuration": configurations[variant], "comparisons": finished[variant]} for variant in variants},
            "implementation": {"experiment": {"filename": Path(__file__).name, "sha256": digest(Path(__file__)), "source": Path(__file__).read_text()},
                               "geometry": source_text(chroma_geometry), "colour_conversion_and_packing": source_text(output_frame)},
            "runtime": {"numpy_version": np.__version__, "python_version": sys.version.split()[0]},
            "helper_implementations": {name: {"filename": Path(sys.modules[name].__file__).name,
                                               "sha256": digest(Path(sys.modules[name].__file__))}
                                       for name in ("diagnose_frame", "compare_output", "dvtunnel", "dvlms", "inverse_stage",
                                                    "summarize_cases", "extract_frame", "import_rpu", "inspect_composition", "reference")},
            "caveats": ["Smaller hardware differences are not proof of accuracy, conformance, or the correct production filter.",
                        "Phase-control variants deliberately use wrong geometry; they are diagnostic negative controls, not candidates for deployment.",
                        "Cubic overshoots are passed to the unchanged direct colour policy, without an extra source clamp.",
                        "All variants use fixed capture-derived masks; no sample exclusions, spatial alignment, fitted offsets or fitted filter coefficients.",
                        "Only final vertical source-chroma expansion varies; BL/EL preparation, MMR guide, reconstruction and enhancement scaling remain unchanged.",
                        "No image artifacts are written. Capture frame identity is the supplied visible-counter association, not an independently verified driver timestamp."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline_output", "result", "extraction", "capture"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = experiment(args.baseline_output, args.result, args.extraction, args.capture)
        save_json(args.report, report)
    except (OSError, KeyError, TypeError, ValueError, np.linalg.LinAlgError) as error:
        parser.exit(1, f"sampling experiment: {error}\n")
    print(json.dumps({"report": str(args.report), "identity": report["identity"], "baseline_byte_identical": True}))


if __name__ == "__main__":
    main()
