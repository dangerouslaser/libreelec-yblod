#!/usr/bin/env python3
"""Offline colour-coordinate conversion and unembedded RGB8 tunnel packing.

Not a playable HDMI frame: dynamic metadata serialization/embedding is separate.
No fitted colour offsets, tone mapping, or proprietary renderer is used.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from extract_frame import digest, save_json
from import_rpu import normalize
from inspect_composition import checked_report, load

# Exact integers signalled by the existing TV-led transport, also observed in
# the SK4 capture. Inverting these avoids an intermediate display-RGB roundtrip.
TARGET_YCC = np.array([[8194, 799, 1681], [8194, -933, 1091],
                       [8194, 267, -5545]], dtype=float) / 8192
TARGET_LMS = np.array([[17080, -348, -348], [-348, 17080, -348],
                       [-348, -348, 17080]], dtype=float) / 16384
TARGET_OFFSET = np.array([0., .5, .5])
# Diagnostic only: existing renderer's HPE LMS -> BT.2020 display RGB matrix.
HPE_TO_RGB = np.array([[3.06441879, -2.16597676, .10155818],
                       [-.65612108, 1.78554118, -.12943749],
                       [.01736321, -.04725154, 1.03004253]])
M1, M2 = 2610 / 16384, 2523 / 32
C1, C2, C3 = 3424 / 4096, 2413 / 128, 2392 / 128


def measured(a):
    if not np.isfinite(a).all():
        raise ValueError("non-finite colour values")
    return {"minimum": float(a.min()), "maximum": float(a.max()),
            "below_zero": int(np.count_nonzero(a < 0)),
            "above_one": int(np.count_nonzero(a > 1))}


def pq_decode(a):
    # Explicit domain policy: negative inputs become zero, positive values above
    # one remain extended. Reject the mathematical pole rather than emit NaNs.
    measured(a)
    p = np.maximum(a, 0) ** (1 / M2)
    denominator = C2 - C3 * p
    if np.any(denominator <= 0):
        raise ValueError("PQ decode outside finite extended domain")
    return (np.maximum(p - C1, 0) / denominator) ** (1 / M1)


def pq_encode(a):
    measured(a)
    p = np.maximum(a, 0) ** M1
    return ((C1 + C2 * p) / (1 + C3 * p)) ** M2


def matrix(m, a):
    return np.einsum("ij,hwj->hwi", m, a)


def expand_left(a, start=0, stop=None):
    """Illustrative bilinear 420-left -> 444, edge replication, float64.

    Chroma centers are (2*x, 2*y + .5) in luma coordinates. No intermediate
    rounding. This is an explicit experiment, not a normative Dolby filter.
    """
    h, w = a.shape
    x = np.arange(w * 2) / 2
    stop = h * 2 if stop is None else stop
    y = (np.arange(start, stop) - .5) / 2
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - ix, y - iy
    rows = (a[np.clip(iy, 0, h - 1)].astype(float) * (1 - fy[:, None])
            + a[np.clip(iy + 1, 0, h - 1)] * fy[:, None])
    return (rows[:, np.clip(ix, 0, w - 1)] * (1 - fx)
            + rows[:, np.clip(ix + 1, 0, w - 1)] * fx)


def source_matrices(dm):
    for key, value in (("compressed", False), ("signal_eotf", 65535),
                       ("signal_eotf_param0", 0), ("signal_eotf_param1", 0),
                       ("signal_eotf_param2", 0), ("signal_bit_depth", 12),
                       ("signal_color_space", 0), ("signal_chroma_format", 0),
                       ("signal_full_range_flag", 1)):
        if dm[key] != value:
            raise ValueError(f"unsupported source {key}")
    ycc = np.array([dm[f"ycc_to_rgb_coef{i}"] for i in range(9)]).reshape(3, 3) / 8192
    offset = np.array([dm[f"ycc_to_rgb_offset{i}"] for i in range(3)]) / 2**28
    lms = np.array([dm[f"rgb_to_lms_coef{i}"] for i in range(9)]).reshape(3, 3) / 16384
    return ycc, offset, lms


def convert(ycc, dm, policy, save):
    if policy not in ("direct", "rgb-bound-diagnostic"):
        raise ValueError("unknown colour policy")
    sm, so, sl = source_matrices(dm)
    nonlinear = matrix(sm, ycc / 4096 - so)
    save("source_nonlinear", nonlinear)
    common = matrix(sl, pq_decode(nonlinear))
    save("common_linear_lms", common)
    if policy == "rgb-bound-diagnostic":
        rgb = matrix(HPE_TO_RGB, common)
        save("diagnostic_rgb_before_bound", rgb)
        common = matrix(np.linalg.inv(HPE_TO_RGB), np.clip(rgb, 0, 1))
    target_linear = matrix(np.linalg.inv(TARGET_LMS), common)
    save("target_linear", target_linear)
    target = matrix(np.linalg.inv(TARGET_YCC), pq_encode(target_linear)) + TARGET_OFFSET
    save("transport_before_quantization", target)
    return np.clip(np.floor(target * 4096 + .5), 0, 4095).astype(np.uint16)


def pack(codes):
    """Co-sited 422 P/T from even pixels; top-down interleaved RGB8."""
    if (codes.ndim != 3 or codes.shape[2] != 3 or codes.shape[1] % 2
            or not np.issubdtype(codes.dtype, np.integer)
            or np.any(codes < 0) or np.any(codes > 4095)):
        raise ValueError("even-width 12-bit integer IPT required")
    intensity = codes[..., 0]
    chroma = np.empty_like(intensity)
    chroma[:, ::2] = codes[:, ::2, 1]
    chroma[:, 1::2] = codes[:, ::2, 2]
    return np.stack([chroma >> 4, intensity >> 4,
                     (intensity & 15) | ((chroma & 15) << 4)], axis=-1).astype(np.uint8)


def provenance(result, extraction):
    report = checked_report(result)
    manifest = report["input_manifest"]
    ex = json.loads((extraction / "extraction.json").read_text())
    if (ex["schema"] != "yblod.extracted-frame.v1" or ex["status"] != "complete"
            or digest(extraction / "extraction.json") != manifest["preparation_details"]["source_extraction_sha256"]
            or digest(extraction / "rpu.json") != ex["rpu_json_sha256"]):
        raise ValueError("source/RPU provenance mismatch")
    rpu = json.loads((extraction / "rpu.json").read_text())
    identity = {"frame_id": f"{ex['source_sha256']}:{ex['source_packet_index_zero_based']}",
                "pts": ex["pts"], "time_base": ex["time_base"]}
    if normalize(rpu, identity) != manifest["metadata"]:
        raise ValueError("composition metadata differs from supplied RPU")
    if (manifest["chroma_location"] != "left" or manifest["format"] != "yuv420p-u16le-lsb"
            or manifest["transfer"] != "pq" or manifest["metadata"]["output_bit_depth"] != 12):
        raise ValueError("12-bit PQ 420-left composer output required")
    return report, rpu["vdr_dm_data"], identity


def render(result, extraction, output, policy):
    result, extraction, output = map(lambda p: Path(p).resolve(), (result, extraction, output))
    report, dm, identity = provenance(result, extraction)
    source_matrices(dm)
    manifest = report["input_manifest"]
    h, w = manifest["height"], manifest["width"]
    planes = []
    for name in ("Y", "Cb", "Cr"):
        shape = (h, w) if name == "Y" else (h // 2, w // 2)
        record = report["stages"][f"reconstructed_{name}"]
        path = (result / record["file"]).resolve()
        if (not path.is_relative_to(result) or path.stat().st_size != int(np.prod(shape)) * 2
                or digest(path) != record["sha256"]):
            raise ValueError("reconstruction plane integrity failed")
        a = np.memmap(path, mode="r", dtype="<u2", shape=shape)
        if np.any(a > 4095):
            raise ValueError("out-of-range reconstructed input")
        planes.append(a)
    # L5 defines final active picture; do not infer borders from pixel brightness.
    areas = [b["Level5"] for b in dm["cmv29_metadata"]["ext_metadata_blocks"] if "Level5" in b]
    if len(areas) != 1:
        raise ValueError("exactly one L5 active area required")
    margins = [areas[0][f"active_area_{side}_offset"] for side in ("left", "right", "top", "bottom")]
    l, r, t, b = margins
    if min(margins) < 0 or l + r >= w or t + b >= h or l % 2 or r % 2:
        raise ValueError("invalid/unsupported active area")
    output.mkdir(parents=True, exist_ok=False)
    stages, streams = {}, {}

    def save(name, array, dtype="<f4"):
        stats = measured(array)
        if name not in stages:
            path = output / (name + (".f32le" if dtype == "<f4" else "." + dtype))
            streams[name] = path.open("xb")
            stages[name] = {"file": path.name, "shape": [h, w, 3], "statistics": stats}
        else:
            total = stages[name]["statistics"]
            total["minimum"] = min(total["minimum"], stats["minimum"])
            total["maximum"] = max(total["maximum"], stats["maximum"])
            for key in ("below_zero", "above_one"):
                total[key] += stats[key]
        array.astype(dtype if dtype == "<f4" else {"u16le": "<u2", "rgb8": "u1"}[dtype]).tofile(streams[name])

    # Bounded working set, no full-frame float intermediates. Source planes are
    # read-only maps; stages stream to disk. Global coordinates preserve seams.
    try:
        for start in range(0, h, 64):
            stop = min(h, start + 64)
            ycc = np.stack([planes[0][start:stop], expand_left(planes[1], start, stop),
                            expand_left(planes[2], start, stop)], axis=-1)
            codes = convert(ycc, dm, policy, save)
            outside = (np.arange(start, stop) < t) | (np.arange(start, stop) >= h-b)
            codes[outside] = [0, 2048, 2048]
            codes[:, :l] = codes[:, w-r:] = [0, 2048, 2048]
            save("transport_ipt444", codes, "u16le")
            save("unembedded_tunnel", pack(codes), "rgb8")
    finally:
        for stream in streams.values():
            stream.close()
    for record in stages.values():
        record["sha256"] = digest(output / record["file"])
    info = {"schema": "yblod.output-reference.v1", "status": "complete",
            "scope": "offline diagnostic; no embedded dynamic metadata; not playable HDMI",
            "identity": identity, "width": w, "height": h, "active_rectangle": [l, t, w-r, h-b],
            "policy": policy, "chroma_expansion": "bilinear-left-edge-replicated-float64",
            "pq_domain": "negative to zero; above one extended; reject decode pole",
            "quantization": "floor(value*4096+0.5), bound 0..4095; no fitted offsets",
            "transport_sampling": "P/T co-sited at even x; top-down RGB8",
            "target_ycc": TARGET_YCC.tolist(), "target_lms": TARGET_LMS.tolist(),
            "target_offset": TARGET_OFFSET.tolist(), "source_dm": dm,
            "composer_report_sha256": digest(result / "report.json"),
            "rpu_sha256": digest(extraction / "rpu.json"),
            "implementation_sha256": digest(Path(__file__)), "numpy_version": np.__version__,
            "stage_storage": "float32 diagnostics; computation float64; integers exact",
            "processing_strip_rows": 64,
            "stages": stages}
    save_json(output / "output.json", info)
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--policy", required=True, choices=("direct", "rgb-bound-diagnostic"))
    args = parser.parse_args()
    try:
        info = render(args.result, args.extraction, args.output, args.policy)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"output: {error}\n")
    print(json.dumps({"output": str(args.output), "policy": info["policy"]}))
