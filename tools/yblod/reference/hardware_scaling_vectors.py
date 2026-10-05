"""Configurable synthetic P010 probes for real VA surfaces; no GPU invocation.

Inputs represent the scaler boundary after native phase preparation, not a
claim about decoded top-left geometry. Identity checks diagnose code transport
before scaling. Optional expectations use the independent informative Annex B
oracle, not a licensed-player capture or an output-fitting procedure.
"""
import argparse
import hashlib
import json
from pathlib import Path

import scaling_oracle
from scaling_probe import CHANNELS, pack_p010, planar_bytes, unpack_p010

NAMES = ("zero", "one", "neutral", "maximum", "channel-tags", "unit-step",
         "x-ramp", "y-ramp", "impulse", "alternating-rows",
         "alternating-columns", "edge-step", "depth-overshoot", "asymmetric-edges")


def dimensions(width, height):
    if (type(width) is not int or type(height) is not int or
            width < 2 or height < 2 or width % 2 or height % 2):
        raise ValueError("even positive integer P010 dimensions of at least 2 required")
    return width, height


def patterns(width=64, height=64):
    """Dimension-independent patterns, never ramping beyond 10-bit code range."""
    dimensions(width, height)
    result = {}
    for name in NAMES:
        planes = {}
        for channel in CHANNELS:
            w, h = (width, height) if channel == "Y" else (width//2, height//2)
            rows = []
            for y in range(h):
                row = []
                for x in range(w):
                    value = 512
                    if name == "zero": value = 0
                    elif name == "one": value = 1
                    elif name == "maximum": value = 1023
                    elif name == "channel-tags": value = {"Y": 512, "Cb": 384, "Cr": 640}[channel]
                    elif name == "unit-step": value += int(x >= w//2)
                    elif name == "x-ramp": value = 384+(256*x)//max(1, w-1)
                    elif name == "y-ramp": value = 384+(256*y)//max(1, h-1)
                    elif name == "impulse": value += 128*int((y, x) == (h//2, w//2))
                    elif name == "alternating-rows": value += 64 if y % 2 else -64
                    elif name == "alternating-columns": value += 64 if x % 2 else -64
                    elif name == "edge-step": value += 128 if x >= w//2 else -128
                    elif name == "depth-overshoot": value = 1023 if x >= w//2 else 0
                    elif name == "asymmetric-edges":
                        # Distinct perimeter codes expose flips, UV swaps, stride
                        # mistakes, and horizontal/vertical edge confusion.
                        if y == 0: value = 400
                        elif y == h-1: value = 620
                        elif x == 0: value = 460
                        elif x == w-1: value = 560
                        if channel == "Cb": value -= 17
                        elif channel == "Cr": value += 23
                    row.append(value)
                rows.append(row)
            planes[channel] = rows
        result[name] = planes
    return result


def input_bytes(name, width=64, height=64):
    if name not in NAMES:
        raise ValueError("unknown synthetic pattern")
    return pack_p010(patterns(width, height)[name])


def check_identity(input_planes, actual_p010):
    """Strict native-code identity; no range remap, tolerated low bits or fit."""
    canonical = pack_p010(input_planes)  # validates rectangularity and depth
    height, width = len(input_planes["Y"]), len(input_planes["Y"][0])
    actual = unpack_p010(actual_p010, width, height)  # rejects every unused low bit
    channels = {}
    for channel in CHANNELS:
        errors = [a-b for expected, observed in zip(input_planes[channel], actual[channel])
                  for b, a in zip(expected, observed)]
        channels[channel] = {"samples": len(errors), "different": sum(e != 0 for e in errors),
                             "maximum_absolute_error": max(abs(e) for e in errors),
                             "mean_absolute_error": sum(abs(e) for e in errors)/len(errors),
                             "mean_signed_error": sum(errors)/len(errors)}
    return {"exact": actual_p010 == canonical, "channels": channels,
            "input_sha256": hashlib.sha256(canonical).hexdigest(),
            "output_sha256": hashlib.sha256(actual_p010).hexdigest(),
            "interpretation": "strict native-code transport check, not scaler or Dolby accuracy"}


def score_scaled(input_planes, actual_p010):
    """Score exact 2x downloaded P010 against the independent u16 baseline.

    Interior excludes eight output samples on each side in EVERY component,
    covering the horizontal eight-tap support at native resolution. Chroma's
    margin is therefore more conservative in physical luma units. Empty
    interiors report zero samples and null error metrics, never an exact pass.
    """
    canonical = pack_p010(input_planes)
    height, width = len(input_planes["Y"]), len(input_planes["Y"][0])
    actual = unpack_p010(actual_p010, width*2, height*2)

    def metrics(errors):
        if not errors:
            return {"samples": 0, "different": 0, "mean_absolute_error": None,
                    "maximum_absolute_error": None, "mean_signed_error": None}
        return {"samples": len(errors), "different": sum(e != 0 for e in errors),
                "mean_absolute_error": sum(abs(e) for e in errors)/len(errors),
                "maximum_absolute_error": max(abs(e) for e in errors),
                "mean_signed_error": sum(errors)/len(errors)}

    channels = {}
    total_overflow = 0
    for channel in CHANNELS:
        expected, _ = scaling_oracle.upsample_el(input_planes[channel], channel)
        h, w = len(expected), len(expected[0])
        errors = [[a-e for a, e in zip(arow, erow)] for arow, erow in zip(actual[channel], expected)]
        flat = [e for row in errors for e in row]
        margin = 8
        interior = [errors[y][x] for y in range(margin, h-margin)
                    for x in range(margin, w-margin)]
        border = [errors[y][x] for y in range(h) for x in range(w)
                  if not (margin <= y < h-margin and margin <= x < w-margin)]
        overflow = sum(s > 1023 for row in expected for s in row)
        total_overflow += overflow
        channels[channel] = dict(metrics(flat), expected_above_10bit_count=overflow,
                                 expected_sha256=hashlib.sha256(planar_bytes(expected)).hexdigest(),
                                 interior_margin_output_samples=margin,
                                 interior=metrics(interior), border=metrics(border),
                                 row_parity={str(p): metrics([e for row in errors[p::2] for e in row])
                                             for p in (0, 1)},
                                 column_parity={str(p): metrics([e for row in errors for e in row[p::2]])
                                                for p in (0, 1)})
    return {"exact": all(c["different"] == 0 for c in channels.values()),
            "input_size": [width, height], "output_size": [width*2, height*2],
            "input_sha256": hashlib.sha256(canonical).hexdigest(),
            "output_sha256": hashlib.sha256(actual_p010).hexdigest(),
            "expected_above_10bit_count": total_overflow, "channels": channels,
            "interpretation": "native-code differences against informative Annex B, not perceptual error or Dolby conformance"}


def generate(destination, width=64, height=64, include_expected=False):
    dimensions(width, height)
    root = Path(destination)
    root.mkdir(exist_ok=False)
    cases = {}

    def record(name, data):
        with (root/name).open("xb") as handle:
            handle.write(data)
        return {"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    for name, planes in patterns(width, height).items():
        case = {"input": record(f"{name}-input.p010", pack_p010(planes)),
                "identity_output_file": f"{name}-identity.p010",
                "scaled_output_file": f"{name}-output.p010"}
        if include_expected:
            expected = {c: scaling_oracle.upsample_el(planes[c], c)[0] for c in CHANNELS}
            case["expected"] = {c: record(f"{name}-expected-{c}.u16le", planar_bytes(expected[c]))
                                for c in CHANNELS}
            case["expected_above_10bit_count"] = sum(
                s > 1023 for c in CHANNELS for row in expected[c] for s in row)
        cases[name] = case
    manifest = {"schema": "yblod.hardware-el-scaling-vectors.v1", "status": "complete",
                "input_size": [width, height], "output_size": [width*2, height*2],
                "bit_depth": 10, "expected_included": include_expected, "cases": cases,
                "storage": "tightly packed little-endian P010; Y then interleaved CbCr, codes in bits15:6",
                "input_chroma_location": "left; after explicit experimental native phase adapter",
                "range": "unmodified enhancement codes; no limited-range expansion",
                "backend_constraints": "dimensions configurable; actual driver support must be queried",
                "reference": "optional informative Annex B u16 expectations; not Dolby conformance",
                "overshoot": "u16 reference may exceed 10bit; stress case is not a supported composer input",
                "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "oracle_sha256": hashlib.sha256(Path(scaling_oracle.__file__).read_bytes()).hexdigest()}
    record("hardware-probes.json", (json.dumps(manifest, indent=2, sort_keys=True)+"\n").encode())
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--include-expected", action="store_true")
    args = parser.parse_args()
    generate(args.destination, args.width, args.height, args.include_expected)
