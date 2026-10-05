"""Safe-band, signed-ramp, base-offset and quality-mode synthetic controls.

Fixed left-to-left request, no geometry fitting or code correction. The native
96-sample band stays128..888 for slope8, providing room for +1/+2 translations
without near-zero clipping ambiguity. Whole-frame covariance is measured, not
assumed. Every copy and every native quality mode gates ALL 2x submissions.
"""
import argparse
from array import array
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import hardware_scaling_large as large
import hardware_chroma_siting_check as siting
import scaling_probe as transport

CHANNELS = transport.CHANNELS
FLAGS = {"default": 0, "fast": 256, "hq": 512}
RAMPS = ("x-8", "x-8-desc", "y-2", "y-2-desc", "y-8", "y-8-desc")
CASES = tuple((p, offset) for p in RAMPS for offset in (0, 1, 2))+(("channel-tags", 0),)
BAND_LENGTH = 96


def band(pattern, component, width, height):
    axis, step, descending = large.descriptor(pattern)
    extent = (width if axis == "x" else height)//(1 if component == "Y" else 2)
    length = min(BAND_LENGTH, extent)
    return (extent-length)//2, length, step, descending


def source_code(pattern, component, x, y, width, height, offset=0):
    if pattern == "channel-tags": return large.TAGS[component]+offset
    axis, _, _ = large.descriptor(pattern)
    start, length, step, descending = band(pattern, component, width, height)
    k = max(0, min(length-1, (x if axis == "x" else y)-start))
    if descending: k = length-1-k
    return 512+step*(k-length//2)+offset


def expected_code(pattern, component, x, y, width, height, scale=2, offset=0):
    if pattern == "channel-tags": return large.TAGS[component]+offset
    if scale == 1: return source_code(pattern, component, x, y, width, height, offset)
    if scale != 2: raise ValueError("identity or exact2x required")
    axis, _, _ = large.descriptor(pattern)
    start, length, step, descending = band(pattern, component, width, height)
    k4 = 2*(x if axis == "x" else y)-(1 if axis == "y" else 0)-4*start
    if descending: k4 = 4*(length-1)-k4
    return (4*(512+offset)+step*(k4-4*(length//2))+2)//4


def generate(path, pattern, offset=0, width=1920, height=1080):
    large.dimensions(width, height)
    if (pattern, offset) not in CASES: raise ValueError("unknown control case")
    vertical = pattern.startswith("y-")
    cached_y = None if vertical else large._bytes(array("H", (source_code(pattern, "Y", x, 0, width, height, offset)<<6 for x in range(width))))
    cached_uv = None if vertical else large._bytes(array("H", (source_code(pattern, c, x, 0, width, height, offset)<<6
                                                           for x in range(width//2) for c in ("Cb", "Cr"))))
    digest = hashlib.sha256()
    with Path(path).open("xb") as handle:
        for chroma, count in ((False, height), (True, height//2)):
            for y in range(count):
                if chroma:
                    data = cached_uv if cached_uv is not None else b"".join((source_code(pattern, c, 0, y, width, height, offset)<<6).to_bytes(2, "little")
                                                                           for c in ("Cb", "Cr"))*(width//2)
                else:
                    data = cached_y if cached_y is not None else (source_code(pattern, "Y", 0, y, width, height, offset)<<6).to_bytes(2, "little")*width
                handle.write(data)
                digest.update(data)
    return {"file": Path(path).name, "bytes": width*height*3, "sha256": digest.hexdigest()}


def _rows(path, width, height):
    with Path(path).open("rb") as handle:
        for chroma, count in ((False, height), (True, height//2)):
            for y in range(count):
                data = handle.read(width*2)
                if len(data) != width*2: raise ValueError("truncated P010")
                words = array("H")
                words.frombytes(data)
                if sys.byteorder != "little": words.byteswap()
                if any(v & 63 for v in words): raise ValueError("P010 unused low bits nonzero")
                yield chroma, y, words, data
        if handle.read(1): raise ValueError("P010 trailing bytes/stride padding")


def _inside(pattern, component, x, y, width, height, scale):
    cw, ch = width*scale, height*scale
    if component != "Y": cw //= 2; ch //= 2
    if pattern == "channel-tags": return 16 <= x < cw-16 and 16 <= y < ch-16
    axis = large.descriptor(pattern)[0]
    start, length, _, _ = band(pattern, component, width, height)
    low, high = scale*start+16, scale*(start+length)-16
    return (low <= x < high and 16 <= y < ch-16) if axis == "x" else (low <= y < high and 16 <= x < cw-16)


def scan(path, pattern, offset, width=1920, height=1080, scale=2):
    large.dimensions(width, height)
    if (pattern, offset) not in CASES or scale not in (1, 2): raise ValueError("unknown control geometry")
    ow, oh = width*scale, height*scale
    states = {c: {"all": large._empty(), "rows": [large._empty(), large._empty()],
                  "columns": [large._empty(), large._empty()], "full_code_samples": 0,
                  "minimum_code": 1023, "maximum_code": 0, "constant_codes_preserved": True} for c in CHANNELS}
    predictions = {}
    axis = None if pattern == "channel-tags" else large.descriptor(pattern)[0]
    for c in CHANNELS:
        if axis is not None:
            extent = (ow if axis == "x" else oh)//(1 if c == "Y" else 2)
            predictions[c] = array("i", (expected_code(pattern, c, m if axis == "x" else 0,
                                                       m if axis == "y" else 0, width, height, scale, offset) for m in range(extent)))
    digest, luma = hashlib.sha256(), hashlib.sha256()
    for chroma, y, words, data in _rows(path, ow, oh):
        digest.update(data)
        if not chroma: luma.update(data)
        cw, ch = (ow//2, oh//2) if chroma else (ow, oh)
        for component_index, c in enumerate(("Cb", "Cr") if chroma else ("Y",)):
            state = states[c]
            if axis is not None:
                start, length, _, _ = band(pattern, c, width, height)
                low, high = scale*start+16, scale*(start+length)-16
            for x in range(cw):
                code = words[x*2+component_index if chroma else x]>>6
                state["full_code_samples"] += 1
                state["minimum_code"] = min(state["minimum_code"], code)
                state["maximum_code"] = max(state["maximum_code"], code)
                if axis is None:
                    state["constant_codes_preserved"] &= code == large.TAGS[c]+offset
                    interior = 16 <= x < cw-16 and 16 <= y < ch-16
                elif axis == "x": interior = low <= x < high and 16 <= y < ch-16
                else: interior = low <= y < high and 16 <= x < cw-16
                if interior:
                    prediction = large.TAGS[c]+offset if axis is None else predictions[c][x if axis == "x" else y]
                    error = code-prediction
                    large._add(state["all"], error)
                    large._add(state["rows"][y%2], error)
                    large._add(state["columns"][x%2], error)
    channels = {c: dict(large._finish(s["all"]), row_parity={str(p): large._finish(s["rows"][p]) for p in (0, 1)},
                        column_parity={str(p): large._finish(s["columns"][p]) for p in (0, 1)},
                        full_code_samples=s["full_code_samples"], minimum_code=s["minimum_code"], maximum_code=s["maximum_code"],
                        constant_codes_preserved=s["constant_codes_preserved"] if axis is None else None) for c,s in states.items()}
    return {"sha256": digest.hexdigest(), "luma_sha256": luma.hexdigest(), "unused_low_bits_zero": True,
            "channels": channels, "margin_output_samples": 16, "native_band_length": BAND_LENGTH,
            "expectation": "rounded pure-axis Annex B first moments plus declared source-code offset; not fitted normalization"}


def compare_offsets(baseline, translated, pattern, offset, width=1920, height=1080, scale=2):
    """Whole-frame and band covariance: observed delta minus declared +offset."""
    ow, oh = width*scale, height*scale
    states = {c: {"full": large._empty(), "interior": large._empty()} for c in CHANNELS}
    a, b = _rows(baseline, ow, oh), _rows(translated, ow, oh)
    for (chroma, y, awords, _), (bchroma, by, bwords, _) in zip(a, b):
        if chroma != bchroma or y != by: raise ValueError("covariance row mismatch")
        cw, ch = (ow//2, oh//2) if chroma else (ow, oh)
        axis = None if pattern == "channel-tags" else large.descriptor(pattern)[0]
        for ci, c in enumerate(("Cb", "Cr") if chroma else ("Y",)):
            if axis is not None:
                start, length, _, _ = band(pattern, c, width, height)
                low, high = scale*start+16, scale*(start+length)-16
            for x in range(cw):
                index = x*2+ci if chroma else x
                error = (bwords[index]>>6)-(awords[index]>>6)-offset
                large._add(states[c]["full"], error)
                interior = (16 <= x < cw-16 and 16 <= y < ch-16) if axis is None else (
                    (low <= x < high and 16 <= y < ch-16) if axis == "x" else (low <= y < high and 16 <= x < cw-16))
                if interior: large._add(states[c]["interior"], error)
    # Force generator EOF checks even when zip stops after its first iterator.
    if next(a, None) is not None or next(b, None) is not None: raise ValueError("covariance unequal frame lengths")
    return {"declared_offset": offset, "channels": {c: {k: large._finish(v) for k,v in s.items()} for c,s in states.items()},
            "interpretation": "diagnostic exact whole-code translation residual; no shift, gain, fit or clamp applied"}


def run(binary, destination, width=1920, height=1080, repeats=2, device="/dev/dri/renderD128"):
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    started = time.monotonic()
    report = {"schema": "yblod.hardware-scaling-controls.v1", "status": "failed", "invocations": [],
              "results": {}, "inputs": {}, "hardware_engine_verified": False,
              "source_sha256": large.file_hash(__file__), "large_helper_sha256": large.file_hash(large.__file__),
              "siting_helper_sha256": large.file_hash(siting.__file__), "transport_helper_sha256": large.file_hash(transport.__file__),
              "kernel": list(os.uname()), "device": str(device), "native_band_length": BAND_LENGTH,
              "interpretation": "fixed left-to-left, safe-band mode/base/sign diagnostics; native gates cover all modes; not fitted geometry or playback performance"}

    def call(pattern, offset, mode, scale, repetition=0):
        stem = f"{mode}-{pattern}-base{offset}-{scale}x-{repetition}"
        output = root/f"{stem}.p010"
        argv = [str(executable), str(device), str(root/f"{pattern}-base{offset}-input.p010"), str(output),
                str(width), str(height), str(width*scale), str(height*scale), mode]
        copy_mode = mode == "copy"
        if not copy_mode: argv += ["--input-chroma", "left", "--output-chroma", "left"]
        entry = {"argv": argv, "output_file": output.name}
        report["invocations"].append(entry)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=60, check=False)
            stdout, stderr = result.stdout, result.stderr
            entry["exit_status"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            entry.update(exit_status=None, timed_out=True)
        except OSError as error:
            stdout, stderr = b"", str(error).encode()
            entry.update(exit_status=None, spawn_error=type(error).__name__)
        for kind, data in (("stdout", stdout), ("stderr", stderr)):
            path = root/f"{stem}.{kind}.log"
            with path.open("xb") as handle: handle.write(data)
            entry[kind] = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest()}
        if output.exists(): entry["output_sha256"] = large.file_hash(output)
        if entry["exit_status"] != 0: raise ValueError("control probe failed/timed out")
        value = json.loads(stdout)
        if value.get("input_size") != [width, height] or value.get("output_size") != [width*scale, height*scale]:
            raise ValueError("control invocation dimensions differ")
        if any(not isinstance(value[k], list) or any(type(n) is not int for n in value[k]) for k in ("input_size", "output_size")):
            raise ValueError("control invocation dimension types invalid")
        flags = 0 if copy_mode else FLAGS[mode]
        if type(value.get("filter_flags")) is not int or value["filter_flags"] != flags:
            raise ValueError("control quality flag differs")
        canonical = dict(value, input_size=[64,64], output_size=[64,64], filter_flags=0)
        siting.validate_invocation(json.dumps(canonical), 64, "left", "left", copy_mode)
        entry["invocation"] = value
        return output, entry

    try:
        large.dimensions(width, height)
        if type(repeats) is not int or not 2 <= repeats <= 4: raise ValueError("2..4 repeats required")
        executable = Path(binary).resolve()
        report.update(binary=str(executable), binary_sha256=large.file_hash(executable),
                      input_size=[width,height], output_size=[width*2,height*2], repeats=repeats)
        for pattern, offset in CASES:
            case = f"{pattern}-base{offset}"
            report["inputs"][case] = generate(root/f"{case}-input.p010", pattern, offset, width, height)
        score_cache, covariance_cache, scaled_paths = {}, {}, {}
        for mode in ("copy", *FLAGS):
            for pattern, offset in CASES:
                case = f"{pattern}-base{offset}"
                path, entry = call(pattern, offset, mode, 1)
                digest = large.file_hash(path)
                key = (pattern, offset, 1, digest)
                if key not in score_cache: score_cache[key] = scan(path, pattern, offset, width, height, 1)
                entry["scan"] = score_cache[key]
                entry["identity_exact"] = digest == report["inputs"][case]["sha256"]
                if not entry["identity_exact"]: raise ValueError(f"native identity failed: {mode}/{case}")
                print(f"controls native complete {mode}/{case}", file=sys.stderr, flush=True)
        report["all_native_quality_gates_complete"] = True
        for mode in FLAGS:
            cases = report["results"].setdefault(mode, {})
            for pattern, offset in CASES:
                case = f"{pattern}-base{offset}"
                paths = [call(pattern, offset, mode, 2, n)[0] for n in range(repeats)]
                hashes = [large.file_hash(path) for path in paths]
                if len(set(hashes)) != 1: raise ValueError("control scaled repeats differ")
                key = (pattern, offset, 2, hashes[0])
                if key not in score_cache: score_cache[key] = scan(paths[0], pattern, offset, width, height, 2)
                result = copy.deepcopy(score_cache[key])
                result.update(repeat_sha256=hashes, repeat_stable=True)
                cases[case] = result
                scaled_paths[mode, pattern, offset] = paths[0]
                if any(c["samples"] == 0 for c in result["channels"].values()): raise ValueError("empty control interior")
                if pattern == "channel-tags" and not all(c["constant_codes_preserved"] for c in result["channels"].values()):
                    raise ValueError("control constants changed")
                if offset:
                    baseline = scaled_paths[mode, pattern, 0]
                    covariance_key = (large.file_hash(baseline), hashes[0], offset, pattern)
                    if covariance_key not in covariance_cache:
                        covariance_cache[covariance_key] = compare_offsets(baseline, paths[0], pattern, offset, width, height)
                    result["base_offset_covariance"] = copy.deepcopy(covariance_cache[covariance_key])
                print(f"controls scaled complete {mode}/{case}", file=sys.stderr, flush=True)
        report["mode_hash_comparison"] = {case: {"sha256": {m: report["results"][m][case]["sha256"] for m in FLAGS},
                                                   "all_equal": len({report["results"][m][case]["sha256"] for m in FLAGS})==1}
                                          for case in report["inputs"]}
        report["status"] = "complete"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report["resources"] = {"elapsed_seconds": time.monotonic()-started, "self_peak_rss_native": usage.ru_maxrss,
                           "rss_native_unit": "bytes" if sys.platform=="darwin" else "KiB",
                           "interpretation": "Python process lifetime peakRSS only; elapsed includes CPU scans, not playback"}
    with (root/"controls-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    args = parser.parse_args()
    result = run(args.binary, args.destination, args.width, args.height, args.repeats, args.device)
    print(json.dumps({"status": result["status"], "report": str(args.destination/"controls-report.json"),
                      "invocations": len(result["invocations"])}))
    raise SystemExit(result["status"] != "complete")
