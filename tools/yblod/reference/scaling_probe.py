#!/usr/bin/env python3
"""Synthetic EL-scaler boundary probes, not a Dolby conformance test.

Expected planes come from the independent Annex-B scalar oracle. P010 is only
a transport representation: codes are not range-expanded or colour-converted.
No GPU is invoked here; score actual downloaded backend results separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import scaling_oracle

CHANNELS = ("Y", "Cb", "Cr")
SCHEMA = "yblod.el-scaling-probes.v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def planar_bytes(rows):
    return b"".join(struct.pack("<" + "H" * len(row), *row) for row in rows)


def pack_p010(planes):
    y, u, v = (planes[c] for c in CHANNELS)
    h, w = len(y), len(y[0])
    if h % 2 or w % 2:
        raise ValueError("even P010 dimensions required")
    for c in CHANNELS:
        hh, ww = (h, w) if c == "Y" else (h // 2, w // 2)
        if len(planes[c]) != hh or any(len(row) != ww for row in planes[c]):
            raise ValueError("inconsistent planes")
        if any(type(s) is not int or not 0 <= s <= 1023 for row in planes[c] for s in row):
            raise ValueError("P010 cannot represent this code without changing it")
    words = [s << 6 for row in y for s in row]
    words.extend(s << 6 for ur, vr in zip(u, v) for pair in zip(ur, vr) for s in pair)
    return struct.pack("<" + "H" * len(words), *words)


def unpack_p010(data, width, height):
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("even positive P010 dimensions required")
    if len(data) != width * height * 3:
        raise ValueError("expected one tightly packed P010 frame, no stride padding")
    words = struct.unpack("<" + "H" * (len(data) // 2), data)
    if any(s & 63 for s in words):
        raise ValueError("P010 low six bits must be zero; no silent precision conversion")
    codes = [s >> 6 for s in words]
    count = width * height
    y = [codes[i:i + width] for i in range(0, count, width)]
    uv = codes[count:]
    u = [uv[i:i + width:2] for i in range(0, len(uv), width)]
    v = [uv[i + 1:i + width:2] for i in range(0, len(uv), width)]
    return dict(zip(CHANNELS, (y, u, v)))


def patterns():
    """Post-phase-adapter scaler inputs; not native top-left decoded frames."""
    result = {}
    for name in ("zero", "one", "neutral", "maximum", "channel-tags", "unit-step",
                 "x-ramp", "y-ramp", "impulse", "alternating-rows",
                 "alternating-columns", "edge-step", "depth-overshoot"):
        planes = {}
        for c in CHANNELS:
            h, w = (16, 16) if c == "Y" else (8, 8)
            rows = []
            for y in range(h):
                row = []
                for x in range(w):
                    value = 512
                    if name == "zero": value = 0
                    elif name == "one": value = 1
                    elif name == "maximum": value = 1023
                    elif name == "channel-tags": value = {"Y": 512, "Cb": 384, "Cr": 640}[c]
                    elif name == "unit-step": value += 1 if x >= w // 2 else 0
                    elif name == "x-ramp": value = 400 + x * 8
                    elif name == "y-ramp": value = 400 + y * 8
                    elif name == "impulse": value += 128 if (y, x) == (h // 2, w // 2) else 0
                    elif name == "alternating-rows": value += 64 if y % 2 else -64
                    elif name == "alternating-columns": value += 64 if x % 2 else -64
                    elif name == "edge-step": value += 128 if x >= w // 2 else -128
                    elif name == "depth-overshoot": value = 1023 if x >= w // 2 else 0
                    row.append(value)
                rows.append(row)
            planes[c] = rows
        result[name] = planes
    return result


def write_new(root, name, data):
    with (root / name).open("xb") as handle:
        handle.write(data)
    return {"file": name, "sha256": sha(data), "bytes": len(data)}


def contract_header():
    return {"schema": SCHEMA, "status": "complete", "input_size": [16, 16],
                "output_size": [32, 32], "bit_depth": 10,
                "storage": "tightly packed little-endian P010: Y then interleaved CbCr; codes in bits15:6",
                "range": "unmodified enhancement codes, not limited-range expansion",
                "input_chroma_location": "left; after explicit native phase adapter",
                "geometry": "Annex B phase convention; see SCALING.md. Do not substitute a centred generic resize silently.",
                "expectation": "informative Annex B reference; not licensed-hardware or Dolby certification",
                "depth_overshoot": "reference u16 bounds can exceed 10bit; this case measures divergence, not a supported composer input",
                "generator_sha256": sha(Path(__file__).read_bytes()),
                "oracle_sha256": sha(Path(scaling_oracle.__file__).read_bytes())}


def canonical_cases():
    for name, inputs in patterns().items():
        expected = {c: scaling_oracle.upsample_el(inputs[c], c)[0] for c in CHANNELS}
        yield name, pack_p010(inputs), {c: planar_bytes(expected[c]) for c in CHANNELS}, sum(
            s > 1023 for c in CHANNELS for row in expected[c] for s in row)


def generate(destination):
    root = Path(destination)
    root.mkdir(exist_ok=False)
    cases = {}
    for name, input_data, expected, overflow in canonical_cases():
        records = {c: write_new(root, f"{name}-expected-{c}.u16le", expected[c]) for c in CHANNELS}
        cases[name] = {"input": write_new(root, f"{name}-input.p010", input_data),
                       "expected": records, "expected_above_10bit_count": overflow,
                       "backend_output_file": f"{name}-output.p010"}
    manifest = dict(contract_header(), cases=cases)
    write_new(root, "probes.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return manifest


def verified_file(root, record):
    path = (root / record["file"]).resolve()
    if path.parent != root.resolve():
        raise ValueError("probe file must remain inside its bundle")
    data = path.read_bytes()
    if len(data) != record["bytes"] or sha(data) != record["sha256"]:
        raise ValueError("probe file hash or size mismatch")
    return data


def score(bundle, outputs, backend):
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError("record device, driver, settings and command as backend provenance")
    root, out = Path(bundle).resolve(), Path(outputs).resolve()
    manifest_data = (root / "probes.json").read_bytes()
    manifest = json.loads(manifest_data)
    if ({k: v for k, v in manifest.items() if k != "cases"} != contract_header()
            or set(manifest["cases"]) != set(patterns())):
        raise ValueError("unsupported or incomplete probe contract")
    cases = {}
    for name, canonical_input, canonical_expected, overflow in canonical_cases():
        case = manifest["cases"][name]
        if verified_file(root, case["input"]) != canonical_input:
            raise ValueError("input differs from canonical synthetic pattern")
        if case["expected_above_10bit_count"] != overflow or set(case["expected"]) != set(CHANNELS):
            raise ValueError("changed expected code contract")
        if case["backend_output_file"] != f"{name}-output.p010":
            raise ValueError("changed backend output path")
        output_data = (out / case["backend_output_file"]).read_bytes()
        actual = unpack_p010(output_data, 32, 32)
        channels = {}
        for c in CHANNELS:
            data = verified_file(root, case["expected"][c])
            if data != canonical_expected[c]:
                raise ValueError("expected values differ from independent oracle")
            w, h = (32, 32) if c == "Y" else (16, 16)
            if len(data) != w * h * 2:
                raise ValueError("expected plane size mismatch")
            expected = struct.unpack("<" + "H" * (w * h), data)
            errors = [s - e for s, e in zip((s for row in actual[c] for s in row), expected)]
            parity = [[errors[y * w + x] for y in range(p, h, 2) for x in range(w)] for p in (0, 1)]
            columns = [[errors[y * w + x] for y in range(h) for x in range(p, w, 2)] for p in (0, 1)]
            channels[c] = {"samples": len(errors), "different": sum(e != 0 for e in errors),
                           "mean_absolute_error": sum(abs(e) for e in errors) / len(errors),
                           "maximum_absolute_error": max(abs(e) for e in errors),
                           "even_row_mean_signed_error": sum(parity[0]) / len(parity[0]),
                           "odd_row_mean_signed_error": sum(parity[1]) / len(parity[1]),
                           "even_column_mean_signed_error": sum(columns[0]) / len(columns[0]),
                           "odd_column_mean_signed_error": sum(columns[1]) / len(columns[1])}
        cases[name] = {"output_sha256": sha(output_data), "channels": channels,
                       "expected_above_10bit_count": case["expected_above_10bit_count"]}
    return {"schema": "yblod.el-scaling-probe-results.v1", "status": "complete",
            "backend": backend, "probe_manifest_sha256": sha(manifest_data),
            "scorer_sha256": sha(Path(__file__).read_bytes()), "cases": cases,
            "interpretation": "Native code errors against informative CPU reference; no correction, alignment fitting, or accuracy certification."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    generator = sub.add_parser("generate")
    generator.add_argument("destination", type=Path)
    scorer = sub.add_parser("score")
    scorer.add_argument("bundle", type=Path)
    scorer.add_argument("outputs", type=Path)
    scorer.add_argument("report", type=Path)
    scorer.add_argument("--backend", required=True, help="device, driver, settings and exact invocation")
    args = parser.parse_args()
    if args.action == "generate":
        generate(args.destination)
    else:
        report = score(args.bundle, args.outputs, args.backend)
        with args.report.open("x") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
