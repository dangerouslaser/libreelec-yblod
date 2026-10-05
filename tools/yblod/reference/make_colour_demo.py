#!/usr/bin/env python3
"""Explicit synthetic colour settings, never an extracted Dolby RPU."""
import argparse
import hashlib
import json
from pathlib import Path

from colour_stage import PQ_POLICIES


def make_configuration(result, destination, *, target, pq_policy):
    if target not in ("identity-diagnostic", "project-transport-diagnostic") or pq_policy not in PQ_POLICIES:
        raise ValueError("explicit supported synthetic target and policy required")
    with (Path(result) / "report.json").open("rb") as handle:
        raw = handle.read((8 << 20) + 1)
    if len(raw) > 8 << 20:
        raise ValueError("report exceeds 8 MiB allowance")
    report = json.loads(raw)
    manifest = report["input_manifest"]
    identity = manifest["metadata"]["frame_id"]
    if (report["schema"] != "yblod.composer-result.v1" or report["status"] != "complete"
            or type(identity) is not str or not identity.startswith("synthetic-")):
        raise ValueError("demo settings require an explicitly synthetic composer result")
    dm = dict(compressed=False, signal_eotf=65535, signal_eotf_param0=0,
        signal_eotf_param1=0, signal_eotf_param2=0, signal_bit_depth=12,
        signal_color_space=0, signal_chroma_format=0, signal_full_range_flag=1)
    for i in range(9):
        dm[f"ycc_to_rgb_coef{i}"] = 8192 if i % 4 == 0 else 0
        dm[f"rgb_to_lms_coef{i}"] = 16384 if i % 4 == 0 else 0
    for i in range(3): dm[f"ycc_to_rgb_offset{i}"] = 0
    if target == "identity-diagnostic":
        ycc = lms = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        offset = [0, 0, 0]
    else:
        ycc = [[v / 8192 for v in row] for row in ((8194, 799, 1681), (8194, -933, 1091), (8194, 267, -5545))]
        lms = [[v / 16384 for v in row] for row in ((17080, -348, -348), (-348, 17080, -348), (-348, -348, 17080))]
        offset = [0, .5, .5]
    config = dict(schema="yblod.colour-frame-config.v1",
        composer_report_sha256=hashlib.sha256(raw).hexdigest(),
        source_dm=dm, target_ycc=ycc, target_lms=lms, target_offset=offset,
        code_scale=4096, pq_policy=pq_policy, chroma_expansion="bilinear-left-diagnostic",
        active_rectangle=[0, 0, manifest["width"], manifest["height"]],
        outside_codes=[round(v * 4096) for v in offset],
        scope="synthetic identity source instructions; not real RPU provenance",
        synthetic_target=target,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with Path(destination).open("x") as handle:
        json.dump(config, handle, indent=2)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("--target", required=True, choices=("identity-diagnostic", "project-transport-diagnostic"))
    parser.add_argument("--pq-policy", required=True, choices=PQ_POLICIES)
    args = parser.parse_args()
    make_configuration(args.result, args.configuration, target=args.target, pq_policy=args.pq_policy)
