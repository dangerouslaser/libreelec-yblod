#!/usr/bin/env python3
"""Compare offline output with a frame-identified CoreELEC VDIN tunnel capture.

Small strips keep memory bounded. Scores are transport code differences, not
perceptual display error. Capture identity is caller-supplied, not inferred.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "accuracy"))
from dvtunnel import crc32_mpeg2, unpack_rgb
from dvlms import matrices, packet
from extract_frame import digest, save_json
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET


def decode_ce(raw):
    h, w, _ = raw.shape
    a = raw.reshape(-1, 8)[:, ::-1].reshape(h, w, 3)
    return unpack_rgb(a[..., 2], a[..., 0], a[..., 1])


def compare(output, capture, identity_file):
    output = Path(output).resolve()
    info = json.loads((output / "output.json").read_text())
    identity = json.loads(Path(identity_file).read_text())
    expected = info["identity"]
    if (info["schema"] != "yblod.output-reference.v1" or info["status"] != "complete"
            or expected["frame_id"] != f"{identity['source_sha256']}:{identity['visible_frame_number']}"
            or expected["pts"] * expected["time_base"][0] * 1000000
            != identity["pts_us"] * expected["time_base"][1]):
        raise ValueError("capture frame identity mismatch")
    h, w = info["height"], info["width"]
    if w * 3 % 8 or h < 4 or w * h < 6144:
        raise ValueError("unsupported capture dimensions")
    rec = info["stages"]["unembedded_tunnel"]
    generated = (output / rec["file"]).resolve()
    if not generated.is_relative_to(output) or digest(generated) != rec["sha256"]:
        raise ValueError("output integrity failed")
    for p in (generated, Path(capture)):
        if p.stat().st_size != h * w * 3:
            raise ValueError("capture/output size mismatch")
    ours = np.memmap(generated, dtype="u1", mode="r", shape=(h, w, 3))
    theirs = np.memmap(capture, dtype="u1", mode="r", shape=(h, w, 3))
    initial = decode_ce(theirs[:max(4, (6144 + w - 1) // w)])
    # At least first and last packets for this two-packet reference. This
    # deliberately rejects other layouts until their framing is supported.
    packets = [packet(*initial, i) for i in range(2)]
    if [p[0] >> 6 for p in packets] != [1, 3] or any(crc32_mpeg2(p) for p in packets):
        raise ValueError("expected two valid SK4 metadata packets")
    for actual, desired in zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS)):
        if not np.array_equal(actual, desired):
            raise ValueError("capture uses different colour coordinates; raw-code comparison invalid")
    l, t, r, b = info["active_rectangle"]
    if t * w + l < 6144:
        raise ValueError("active rectangle overlaps metadata; explicit exclusion needed")
    totals = {name: {"samples": 0, "absolute_sum": 0, "square_sum": 0,
                     "maximum_absolute_codes": 0, "over_sixteen": 0} for name in ("I", "P", "T")}
    for start in range(t, b, 64):
        stop = min(b, start + 64)
        oi, oc = unpack_rgb(*np.moveaxis(ours[start:stop], -1, 0))
        si, sc = decode_ce(theirs[start:stop])
        for name, a, c in (("I", oi[:, l:r], si[:, l:r]),
                           ("P", oc[:, l:r:2], sc[:, l:r:2]),
                           ("T", oc[:, l+1:r:2], sc[:, l+1:r:2])):
            delta = np.abs(a.astype(np.int64) - c)
            total = totals[name]
            total["samples"] += delta.size
            total["absolute_sum"] += int(delta.sum())
            total["square_sum"] += int((delta * delta).sum())
            total["maximum_absolute_codes"] = max(total["maximum_absolute_codes"], int(delta.max()))
            total["over_sixteen"] += int(np.count_nonzero(delta > 16))
    for total in totals.values():
        n = total["samples"]
        total["mean_absolute_codes"] = total.pop("absolute_sum") / n
        total["rmse_codes"] = (total.pop("square_sum") / n) ** .5
        total["over_sixteen_codes_percent"] = 100 * total.pop("over_sixteen") / n
    return {"scope": "SK4 transport comparison; not displayed colour accuracy or proof of Dolby compliance",
            "identity": expected, "identity_basis": "supplied visible-counter/source association; not driver PTS",
            "capture_sha256": digest(Path(capture)), "identity_file_sha256": digest(Path(identity_file)),
            "output_report_sha256": digest(output / "output.json"), "policy": info["policy"],
            "implementation_sha256": digest(Path(__file__)), "active_rectangle": [l, t, r, b],
            "metadata_first_copy_crc": [True, True], "transport_matrices_equal": True,
            "channels": totals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("capture_identity", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = compare(args.output_directory, args.capture, args.capture_identity)
        save_json(args.report, report)
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f"comparison: {error}\n")
    print(json.dumps(report, indent=2))
