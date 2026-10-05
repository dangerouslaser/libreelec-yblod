#!/usr/bin/env python3
"""Prepare native 2x P7 layers for the left-sited, 4:2:0 reference composer.

ETSI GS CCM 001 V1.1.1 clause 5.4.2.3.3 and informative annex B.
The explicit top-left -> left conversion is an experimental input adapter,
not a claim about a proprietary Dolby implementation. Requires NumPy.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from extract_frame import digest, save_json
from import_rpu import normalize
from reference import CHANNELS, SCHEMA, read_plane, validate

SPEC_SHA256 = "c711442055e73c88be8380317c388d5d9f1992a0fd1fc4bc1f549566a4685b2c"
H_OFFSETS = (-3, -2, -1, 0, 1, 2, 3, 4)
H_WEIGHTS = (22, 94, -524, 2456, 2456, -524, 94, 22)


def plane(values):
    values = np.asarray(values)
    if values.ndim != 2 or 0 in values.shape or values.dtype.kind not in "ui":
        raise ValueError("expected a nonempty two-dimensional integer plane")
    if np.any(values < 0) or np.any(values > 65535):
        raise ValueError("sample exceeds u16 storage range")
    return values.astype(np.int64)


def fir(values, axis, offsets, weights, shift, maximum):
    """Edge-replicated integer FIR; round and bound after this pass."""
    values = plane(values)
    if axis not in (0, 1) or len(offsets) != len(weights) or sum(weights) != 1 << shift:
        raise ValueError("invalid FIR kernel")
    indices = np.arange(values.shape[axis])
    accumulator = np.zeros_like(values)
    for offset, weight in zip(offsets, weights):
        accumulator += weight * np.take(values, np.clip(indices + offset, 0, len(indices) - 1), axis=axis)
    rounded = (accumulator + (1 << (shift - 1))) >> shift
    stats = {"below_zero_before_bound": int(np.count_nonzero(rounded < 0)),
             "above_maximum_before_bound": int(np.count_nonzero(rounded > maximum)),
             "unbounded_minimum": int(rounded.min()), "unbounded_maximum": int(rounded.max()),
             "maximum": maximum, "axis": axis, "offsets": list(offsets),
             "weights": list(weights), "shift": shift}
    return np.clip(rounded, 0, maximum), stats


def chroma_to_left(values, location, bit_depth, method):
    """Evaluate chroma at row j+1/4: top-left y=2j -> left y=2j+1/2."""
    values = plane(values)
    if method not in ("linear", "cubic128") or location not in ("left", "topleft"):
        raise ValueError("unsupported chroma preparation policy")
    if values.max() >= 1 << bit_depth:
        raise ValueError("input chroma exceeds its bit depth")
    if location == "left":
        return values, {"operation": "identity", "input_location": location, "output_location": "left"}
    if method == "linear":
        result, stats = fir(values, 0, (0, 1), (3, 1), 2, (1 << bit_depth) - 1)
    else:
        result, stats = fir(values, 0, (-1, 0, 1, 2), (-9, 111, 29, -3), 7, (1 << bit_depth) - 1)
    stats.update(operation="quarter_chroma_row_shift", method=method,
                 input_location=location, output_location="left",
                 coordinate="output[j,x] samples input[j+1/4,x]",
                 evidence="explicit experimental phase-conversion filter, not prescribed by CCM")
    return result, stats


def upsample_el(values, component):
    """Literal annex B.3/B.2 example: vertical then horizontal, u16 bounds.

    Input/output values retain their code scale. The caller must reject a result
    outside the declared EL depth, rather than invent an additional clamp.
    """
    values = plane(values)
    if component == "Y":
        even, a = fir(values, 0, (-2, -1, 0, 1), (-3, 29, 111, -9), 7, 65535)
        odd, b = fir(values, 0, (-1, 0, 1, 2), (-9, 111, 29, -3), 7, 65535)
    elif component in ("Cb", "Cr"):
        even, a = fir(values, 0, (-1, 0), (64, 192), 8, 65535)
        odd, b = fir(values, 0, (0, 1), (192, 64), 8, 65535)
    else:
        raise ValueError("unknown component")
    vertical = np.empty((values.shape[0] * 2, values.shape[1]), dtype=np.int64)
    vertical[::2], vertical[1::2] = even, odd
    horizontal_odd, c = fir(vertical, 1, H_OFFSETS, H_WEIGHTS, 12, 65535)
    result = np.empty((vertical.shape[0], vertical.shape[1] * 2), dtype=np.int64)
    result[:, ::2], result[:, 1::2] = vertical, horizontal_odd
    return result, vertical, {"vertical_even": a, "vertical_odd": b, "horizontal_odd": c,
                              "horizontal_even": "copy input", "evidence": "CCM annex B (informative)"}


def mmr_luma_left(values):
    """Clause 5.4.2.3.3: horizontal [1,2,1]/4, then average row pairs.

    Round each horizontal row first, then round the two-row average. The output
    samples are centered at x=2i, y=2j+1/2, matching prepared left-sited chroma.
    """
    values = plane(values)
    if values.shape[0] % 2 or values.shape[1] % 2:
        raise ValueError("MMR luma preparation requires even dimensions")
    horizontal, stats = fir(values, 1, (-1, 0, 1), (1, 2, 1), 2, 65535)
    result = (horizontal[::2, ::2] + horizontal[1::2, ::2] + 1) >> 1
    return result, {"horizontal": stats, "vertical": "(row[2j] + row[2j+1] + 1) >> 1",
                    "position_in_luma_samples": ["2i", "2j+1/2"],
                    "evidence": "CCM clause 5.4.2.3.3; visually checked equation"}


def save_plane(directory, name, values):
    values = plane(values)
    data = values.astype("<u2").tobytes()
    with (directory / name).open("xb") as handle:
        handle.write(data)
    return {"file": name, "width": values.shape[1], "height": values.shape[0],
            "minimum": int(values.min()), "maximum": int(values.max()),
            "sha256": hashlib.sha256(data).hexdigest()}


def prepare(extraction_dir, output, phase_filter):
    extraction_dir, output = Path(extraction_dir).resolve(), Path(output).resolve()
    extraction = json.loads((extraction_dir / "extraction.json").read_text())
    composition = json.loads((extraction_dir / "composition.json").read_text())
    verification = json.loads((extraction_dir / "verification/verification.json").read_text())
    if extraction["schema"] != "yblod.extracted-frame.v1" or extraction["status"] != "complete":
        raise ValueError("completed extraction required")
    if verification["status"] != "complete" or not verification["metadata_normalization_exact"]:
        raise ValueError("successful extraction verification required")
    if not extraction["rpu_matches_source_packet_and_global_index"]:
        raise ValueError("unverified frame association")
    extraction_hash, composition_hash = digest(extraction_dir / "extraction.json"), digest(extraction_dir / "composition.json")
    if (composition["source_extraction_sha256"] != extraction_hash
            or verification["extraction_sha256"] != extraction_hash
            or verification["composition_sha256"] != composition_hash
            or digest(extraction_dir / "rpu.json") != extraction["rpu_json_sha256"]
            or digest(extraction_dir / "frame.rpu.bin") != extraction["rpu_sha256"]):
        raise ValueError("extraction/instruction provenance mismatch")
    metadata = composition["metadata"]
    identity = {"frame_id": f"{extraction['source_sha256']}:{extraction['source_packet_index_zero_based']}",
                "pts": extraction["pts"], "time_base": extraction["time_base"]}
    rpu = json.loads((extraction_dir / "rpu.json").read_text())
    if normalize(rpu, identity) != metadata:
        raise ValueError("normalized instructions changed")
    if rpu["header"]["chroma_resampling_explicit_filter_flag"]:
        raise ValueError("explicit source resampling filters are not supported")
    bl_info, el_info = extraction["layers"]["bl"], extraction["layers"]["el"]
    width, height = bl_info["width"], bl_info["height"]
    if (width, height) != (el_info["width"] * 2, el_info["height"] * 2):
        raise ValueError("this experiment requires exactly 2x native BL/EL dimensions")
    if any(info["stream"]["color_transfer"] != "smpte2084" for info in (bl_info, el_info)):
        raise ValueError("only PQ inputs supported")
    if phase_filter not in ("linear", "cubic128"):
        raise ValueError("select linear or cubic128 phase conversion explicitly")
    inputs, input_hashes = {}, {}
    for layer, info in (("bl", bl_info), ("el", el_info)):
        if info["chroma_location"] not in ("left", "topleft"):
            raise ValueError("unsupported native chroma location")
        if not verification["layers"][layer]["single_and_four_thread_decodes_identical"]:
            raise ValueError("native decode was not reproducible")
        depth = metadata[f"{layer}_bit_depth"]
        inputs[layer] = {}
        for channel in CHANNELS:
            factor = 1 if channel == "Y" else 2
            shape = info["height"] // factor, info["width"] // factor
            record = info["planes"][channel]
            samples = read_plane(extraction_dir, record["file"], shape[0] * shape[1], depth, input_hashes)
            if input_hashes[record["file"]] != record["sha256"]:
                raise ValueError(f"{layer}/{channel}: original plane changed")
            inputs[layer][channel] = np.asarray(samples).reshape(shape).astype(np.int64)
    output.mkdir(exist_ok=False)
    stages, operations, scaler_inputs = {}, {}, {}
    prepared = {"bl": {}, "el": {}}
    for layer, info in (("bl", bl_info), ("el", el_info)):
        for channel in CHANNELS:
            values = inputs[layer][channel]
            if channel != "Y":
                values, operation = chroma_to_left(values, info["chroma_location"],
                                                    metadata[f"{layer}_bit_depth"], phase_filter)
                operations[f"{layer}_{channel}_phase"] = operation
                stages[f"{layer}_{channel}_phase"] = save_plane(output, f"{layer}_{channel}_phase.u16le", values)
            if layer == "el":
                # This explicit checkpoint is the future hardware-backend test
                # boundary. A production backend may fuse preparation, but must
                # declare all phase/range/format changes rather than hide them.
                scaler_inputs[channel] = save_plane(output, f"el_{channel}_scaler_input.u16le", values)
                values, vertical, operation = upsample_el(values, channel)
                operations[f"el_{channel}_upscale"] = operation
                stages[f"el_{channel}_vertical"] = save_plane(output, f"el_{channel}_vertical.u16le", vertical)
            if int(values.max()) >= 1 << metadata[f"{layer}_bit_depth"]:
                raise ValueError(f"{layer}/{channel}: annex B result exceeds declared input depth; no implicit extra clamp")
            name = f"{layer}_{channel}.u16le"
            stages[f"{layer}_{channel}"] = save_plane(output, name, values)
            prepared[layer][channel] = name
    guide, operation = mmr_luma_left(inputs["bl"]["Y"])
    operations["mmr_luma"] = operation
    stages["mmr_luma"] = save_plane(output, "mmr_luma.u16le", guide)
    details = {"policy": f"top-left-to-left-{phase_filter}-then-ccm-annex-b",
               "execution_role": "offline CPU reference only; not a production scaler requirement",
               "phase_filter": phase_filter, "native_chroma_locations": {"bl": bl_info["chroma_location"], "el": el_info["chroma_location"]},
               "output_chroma_location": "left", "specification_pdf_sha256": SPEC_SHA256,
               "source_extraction_sha256": extraction_hash, "source_composition_sha256": composition_hash,
               "source_verification_sha256": digest(extraction_dir / "verification/verification.json"),
               "source_plane_sha256": input_hashes, "preparer_sha256": digest(__file__),
               "numpy_version": np.__version__, "operations": operations, "stages": stages,
               "geometry_assumption": "annex B: EL luma output uses co-sited horizontal and quarter-phase vertical filters; converted left-sited chroma uses its separate vertical filter",
               "accuracy_status": "experimental preparation policy; not validated against hardware"}
    scaler_contract = {"schema": "yblod.el-scaling-job.v1", "identity": identity,
                       "backend": "cpu-ccm-annex-b-reference", "role": "comparison baseline, not mandatory playback backend",
                       "input": {"width": el_info["width"], "height": el_info["height"],
                                 "bit_depth": metadata["el_bit_depth"], "chroma_location": "left",
                                 "format": "yuv420p-u16le-lsb", "planes": scaler_inputs},
                       "output": {"width": width, "height": height,
                                  "bit_depth": metadata["el_bit_depth"], "chroma_location": "left",
                                  "format": "yuv420p-u16le-lsb",
                                  "planes": {c: stages[f"el_{c}"] for c in CHANNELS}},
                       "geometry": details["geometry_assumption"],
                       "source_native_chroma_location": el_info["chroma_location"],
                       "preparation_before_scaling": phase_filter,
                       "does_not_apply_rpu_or_combine_layers": True,
                       "hardware_evaluation": "Compare actual Intel Quick Sync / supported AMD output, phase, precision and total transfer cost; do not assume identical filters or format support."}
    save_json(output / "el-scaling-job.json", scaler_contract)
    details["el_scaling_job_sha256"] = digest(output / "el-scaling-job.json")
    manifest = {"schema": SCHEMA, "width": width, "height": height, "format": "yuv420p-u16le-lsb",
                "transfer": "pq", "chroma_location": "left", "metadata": metadata,
                "bl": dict(identity, planes=prepared["bl"]), "el": dict(identity, planes=prepared["el"]),
                "mmr_luma": "mmr_luma.u16le", "preparation_details": details,
                "preparation": f"Actual top-left to left chroma conversion ({phase_filter}) at each native layer resolution; EL upscaled 2x using literal informative annex B; BL luma unchanged; MMR luma from clause 5.4.2.3.3. See preparation_details for assumptions and hashes."}
    validate(manifest)
    # Only the presence of this final manifest denotes a completed preparation.
    save_json(output / "frame.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("output", type=Path, help="new prepared bundle directory")
    parser.add_argument("--phase-filter", choices=("linear", "cubic128"), required=True)
    args = parser.parse_args()
    try:
        prepare(args.extraction, args.output, args.phase_filter)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"preparation: {error}\n")
    print(args.output / "frame.json")
