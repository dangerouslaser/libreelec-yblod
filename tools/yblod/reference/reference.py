#!/usr/bin/env python3
"""Offline integer composer experiment; NOT a complete Dolby Vision renderer.

Arithmetic basis: ETSI GS CCM 001 V1.1.1, clauses 5.4.2 and 5.4.3.
See README.md for supported inputs, deliberate limitations and interpretations.
"""
import argparse
from array import array
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "yblod.composer-frame.v1"
CHANNELS = ("Y", "Cb", "Cr")
SPEC = "https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf"


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: expected integer in [{low}, {high}]")
    return value


def clip(value, low, high):
    return min(high, max(low, value))


def polynomial(sample, coefficients, bit_depth, denominator):
    """Map an already pivot-clamped sample to unsigned 16-bit codes."""
    total = sum(coefficient * sample ** power * (1 << (20 - bit_depth * power))
                for power, coefficient in enumerate(coefficients))
    return clip(total >> (denominator + 4), 0, 65535)


def mmr(samples, constant, coefficients, bit_depth, denominator):
    """MMR on already pivot-clamped Y/Cb/Cr at one chroma position.

    Each row contains Y, Cb, Cr, Y*Cb, Y*Cr, Cb*Cr, Y*Cb*Cr terms.
    Preserve intermediate fixed-point truncations, especially cubic terms.
    """
    y, cb, cr = samples
    first = [v << (20 - bit_depth) for v in samples]
    first += [a * b << (20 - 2 * bit_depth)
              for a, b in ((y, cb), (y, cr), (cb, cr))]
    first.append((first[3] * first[2]) >> 20)
    second = [(v * v) << (20 - 2 * bit_depth) for v in samples]
    second += [(v * v) >> 20 for v in first[3:]]
    third = [(a * b) >> 20 for a, b in zip(first, second)]
    total = constant << 20
    for row, terms in zip(coefficients, (first, second, third)):
        total += sum(coefficient * term for coefficient, term in zip(row, terms))
    return clip(total >> (denominator + 4), 0, 65535)


def inverse_el(sample, parameters, bit_depth, denominator):
    """Recover signed correction. Python integers avoid accumulator overflow."""
    distance = sample - parameters["offset"]
    if distance == 0:
        return 0
    direction = 1 if distance > 0 else -1
    gain = 1 << (10 - bit_depth)
    correction = ((2 * distance - direction) * parameters["slope"]
                  + 2 * direction * parameters["threshold"]) * gain
    limit = 2 * gain * parameters["maximum"]
    correction = clip(correction, -limit, limit)
    return correction >> (denominator - 5 - bit_depth)


def reconstruct(mapped, residual, output_depth):
    """Add first, round once, then bound to the output code range."""
    shift = 16 - output_depth
    return clip((mapped + residual + (1 << (shift - 1))) >> shift,
                0, (1 << output_depth) - 1)


def map_sample(component, samples, mappings, bit_depth, denominator):
    mapping = mappings[component]
    pivots = mapping["pivots"]
    # Endpoint interpretation: the last interval owns the upper endpoint.
    index = clip(bisect_right(pivots, samples[component]) - 1,
                 0, len(mapping["segments"]) - 1)
    segment = mapping["segments"][index]
    bounded = [clip(value, m["pivots"][0], m["pivots"][-1])
               for value, m in zip(samples, mappings)]
    if segment["method"] == "polynomial":
        return polynomial(bounded[component], segment["coefficients"],
                          bit_depth, denominator)
    return mmr(bounded, segment["constant"], segment["coefficients"],
               bit_depth, denominator)


def frame_identity(record):
    if not isinstance(record["frame_id"], str) or not record["frame_id"]:
        raise ValueError("frame_id must be a nonempty string")
    pts = integer(record["pts"], "pts", -(1 << 63), (1 << 63) - 1)
    tb = record["time_base"]
    if not isinstance(tb, list) or len(tb) != 2:
        raise ValueError("time_base must be [numerator, denominator]")
    for part in tb:
        integer(part, "time_base", 1, (1 << 31) - 1)
    return record["frame_id"], pts, tuple(tb)


def validate(manifest):
    if manifest["schema"] != SCHEMA:
        raise ValueError("unsupported manifest schema")
    if manifest["format"] != "yuv420p-u16le-lsb" or manifest["transfer"] != "pq":
        raise ValueError("only prepared planar 4:2:0, PQ, right-aligned u16le is supported")
    width = integer(manifest["width"], "width", 2, 8192)
    height = integer(manifest["height"], "height", 2, 8192)
    if width % 2 or height % 2:
        raise ValueError("4:2:0 dimensions must be even")
    if manifest["chroma_location"] != "left":
        raise ValueError("only declared left/vertically centered chroma is supported")
    if not isinstance(manifest["preparation"], str) or not manifest["preparation"].strip():
        raise ValueError("preparation must document EL alignment/scaling and MMR luma preparation")
    metadata = manifest["metadata"]
    identity = frame_identity(manifest["bl"])
    if frame_identity(metadata) != identity:
        raise ValueError("base layer and metadata frame identities differ")
    bl_depth = integer(metadata["bl_bit_depth"], "bl_bit_depth", 8, 10)
    el_depth = integer(metadata["el_bit_depth"], "el_bit_depth", 8, 10)
    if bl_depth not in (8, 10) or el_depth not in (8, 10):
        raise ValueError("input depths must be 8 or 10")
    if metadata["output_bit_depth"] not in (10, 12) or type(metadata["output_bit_depth"]) is not int:
        raise ValueError("output_bit_depth must be 10 or 12")
    denominator = integer(metadata["coefficient_log2_denom"], "coefficient_log2_denom", el_depth + 5, 32)
    if type(metadata["disable_residual"]) is not bool:
        raise ValueError("disable_residual must be boolean")
    if manifest.get("el") is not None:
        if frame_identity(manifest["el"]) != identity:
            raise ValueError("base and enhancement layer frame identities differ")
    elif not metadata["disable_residual"]:
        raise ValueError("enhancement layer is required; refusing silent base-only fallback")
    mappings = metadata["mappings"]
    if not isinstance(mappings, list) or len(mappings) != 3:
        raise ValueError("exactly three component mappings required")
    for component, mapping in enumerate(mappings):
        pivots = mapping["pivots"]
        if not isinstance(pivots, list) or not 2 <= len(pivots) <= 17:
            raise ValueError("each mapping requires 2..17 absolute pivots")
        for pivot in pivots:
            integer(pivot, "pivot", 0, (1 << bl_depth) - 1)
        if any(a >= b for a, b in zip(pivots, pivots[1:])):
            raise ValueError("pivots must be strictly increasing")
        if len(mapping["segments"]) != len(pivots) - 1:
            raise ValueError("one mapping segment per pivot interval required")
        for segment in mapping["segments"]:
            coefficients = segment["coefficients"]
            if segment["method"] == "polynomial":
                if not isinstance(coefficients, list) or len(coefficients) not in (2, 3):
                    raise ValueError("polynomial must be linear or quadratic")
                flat = coefficients
                low, high = -(64 << denominator), (64 << denominator) - 1
            elif segment["method"] == "mmr" and component != 0:
                if not isinstance(coefficients, list) or not 1 <= len(coefficients) <= 3:
                    raise ValueError("MMR requires 1..3 orders")
                if any(not isinstance(row, list) or len(row) != 7 for row in coefficients):
                    raise ValueError("each MMR order requires seven coefficients")
                flat = [segment["constant"]] + [v for row in coefficients for v in row]
                low, high = -(65536 << denominator), (65536 << denominator) - 1
            else:
                raise ValueError("unsupported mapping method (MMR is chroma-only)")
            for coefficient in flat:
                integer(coefficient, "fixed-point coefficient", low, high)
    if not metadata["disable_residual"]:
        if metadata["nlq_method"] != "linear_deadzone":
            raise ValueError("only linear_deadzone enhancement processing is supported")
        if len(metadata["nlq"]) != 3:
            raise ValueError("three NLQ parameter sets required")
        for parameters in metadata["nlq"]:
            integer(parameters["offset"], "offset", 0, (1 << el_depth) - 1)
            for key in ("slope", "threshold", "maximum"):
                integer(parameters[key], key, 0, (2 << denominator) - 1)


def read_plane(root, filename, count, bit_depth, hashes):
    if not isinstance(filename, str):
        raise ValueError("plane path must be a relative filename")
    path = (root / filename).resolve()
    if Path(filename).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("plane paths must stay inside the input bundle")
    if path.stat().st_size != 2 * count:
        raise ValueError(f"{filename}: expected exactly {count} u16le samples")
    raw = path.read_bytes()
    samples = array("H")
    if samples.itemsize != 2:
        raise ValueError("unsupported Python array representation")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    if max(samples) >= 1 << bit_depth:
        raise ValueError(f"{filename}: samples exceed declared depth; inputs must be right-aligned")
    hashes[filename] = hashlib.sha256(raw).hexdigest()
    return samples


def write_plane(directory, name, samples):
    low, high = min(samples), max(samples)
    if sys.byteorder != "little":
        samples.byteswap()
    raw = samples.tobytes()
    with (directory / name).open("xb") as handle:
        handle.write(raw)
    return {"file": name, "samples": len(samples), "minimum": low, "maximum": high,
            "sha256": hashlib.sha256(raw).hexdigest()}


def run(manifest_path, output):
    manifest_path, output = Path(manifest_path), Path(output)
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    validate(manifest)
    metadata = manifest["metadata"]
    counts = [manifest["width"] * manifest["height"]]
    counts += [counts[0] // 4] * 2
    hashes = {}
    root = manifest_path.parent
    bl = [read_plane(root, manifest["bl"]["planes"][c], n,
                     metadata["bl_bit_depth"], hashes) for c, n in zip(CHANNELS, counts)]
    enabled = not metadata["disable_residual"]
    el = ([read_plane(root, manifest["el"]["planes"][c], n,
                      metadata["el_bit_depth"], hashes) for c, n in zip(CHANNELS, counts)]
          if enabled else None)
    needs_mmr = any(s["method"] == "mmr" for m in metadata["mappings"] for s in m["segments"])
    guide = None
    if needs_mmr:
        if not manifest.get("mmr_luma"):
            raise ValueError("MMR needs an explicitly prepared luma plane on the chroma grid")
        guide = read_plane(root, manifest["mmr_luma"], counts[1], metadata["bl_bit_depth"], hashes)
    if array("i").itemsize != 4:
        raise ValueError("32-bit signed stage storage is required")
    # Exclusive directory: never overwrite a previous run. Completion report is written last.
    output.mkdir(parents=False, exist_ok=False)
    report = {"schema": "yblod.composer-result.v1", "status": "complete",
              "scope": "prepared-input reconstruction only; not HDMI or display-referred RGB",
              "specification": SPEC, "input_manifest": manifest,
              "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
              "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "input_sha256": hashes, "stages": {}}
    for component, (channel, count) in enumerate(zip(CHANNELS, counts)):
        mapped, residual, summed, result = array("H"), array("i"), array("i"), array("H")
        for index in range(count):
            if component == 0:
                samples = (bl[0][index], 0, 0)
            else:
                samples = (guide[index] if guide is not None else 0, bl[1][index], bl[2][index])
            value = map_sample(component, samples, metadata["mappings"],
                               metadata["bl_bit_depth"], metadata["coefficient_log2_denom"])
            correction = (inverse_el(el[component][index], metadata["nlq"][component],
                                     metadata["el_bit_depth"], metadata["coefficient_log2_denom"])
                          if enabled else 0)
            mapped.append(value)
            residual.append(correction)
            summed.append(value + correction)
            result.append(reconstruct(value, correction, metadata["output_bit_depth"]))
        for stage, values, suffix in (("mapped", mapped, "u16le"),
                                      ("residual", residual, "i32le"),
                                      ("sum", summed, "i32le"),
                                      ("reconstructed", result, "u16le")):
            report["stages"][f"{stage}_{channel}"] = write_plane(
                output, f"{stage}_{channel}.{suffix}", values)
    with (output / "report.json").open("x") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path, help="new directory (must not already exist)")
    args = parser.parse_args()
    try:
        run(args.manifest, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"reference: {error}\n")
    print(f"Reconstruction stages saved to {args.output}; see report.json")


if __name__ == "__main__":
    main()
