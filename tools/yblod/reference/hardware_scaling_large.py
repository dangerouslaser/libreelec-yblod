"""Row-streamed production-size synthetic scaling diagnostics, never fitting.

Only an axis-isolated affine band is scored against rounded Annex B first
moments. For x ramps the vertical pass preserves constants; for y ramps the
horizontal pass does likewise, so one explicit half-positive rounding suffices.
Changing input-siting declarations reinterprets identical bytes on different
physical grids. Results do not establish Dolby geometry or hardware routing.
"""
import argparse
from array import array
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from hardware_chroma_siting_check import CONFIGURATIONS, validate_invocation
import hardware_chroma_siting_check as siting_helper
import scaling_probe as transport_helper
from scaling_probe import CHANNELS

PATTERNS = ("channel-tags", "x-8", "y-1", "y-1-desc", "y-2", "y-2-desc",
            "y-4", "y-4-desc", "y-8", "y-8-desc")
TAGS = {"Y": 512, "Cb": 384, "Cr": 640}


def dimensions(width, height):
    if (type(width) is not int or type(height) is not int or width < 64 or height < 64
            or width % 2 or height % 2 or width > 1920 or height > 1080):
        raise ValueError("even 64..1920 by 64..1080 input dimensions required")


def descriptor(pattern):
    if pattern == "channel-tags": return None
    parts = pattern.split("-")
    if (len(parts) not in (2, 3) or parts[0] not in ("x", "y") or parts[1] not in ("1", "2", "4", "8")
            or len(parts) == 3 and parts[2] != "desc"):
        raise ValueError("unknown synthetic pattern")
    return parts[0], int(parts[1]), len(parts) == 3


def band(pattern, component, width, height):
    axis, step, descending = descriptor(pattern)
    extent = width if axis == "x" else height
    if component != "Y": extent //= 2
    length = min(128, extent)
    return (extent-length)//2, length, step, descending


def source_code(pattern, component, x, y, width, height):
    if pattern == "channel-tags": return TAGS[component]
    axis, _, _ = descriptor(pattern)
    start, length, step, descending = band(pattern, component, width, height)
    k = max(0, min(length-1, (x if axis == "x" else y)-start))
    if descending: k = length-1-k
    return 512+step*(k-length//2)


def expected_code(pattern, component, x, y, width, height, scale=2):
    """Rounded first-moment prediction INSIDE the declared affine band only."""
    if pattern == "channel-tags": return TAGS[component]
    if scale == 1: return source_code(pattern, component, x, y, width, height)
    if scale != 2: raise ValueError("only identity or exact 2x supported")
    axis, _, _ = descriptor(pattern)
    start, length, step, descending = band(pattern, component, width, height)
    coordinate4 = 2*(x if axis == "x" else y)-(1 if axis == "y" else 0)-4*start
    if descending: coordinate4 = 4*(length-1)-coordinate4
    numerator = 4*512+step*(coordinate4-4*(length//2))
    return (numerator+2)//4


def _bytes(words):
    if sys.byteorder != "little": words.byteswap()
    return words.tobytes()


def generate(path, pattern, width=1920, height=1080):
    dimensions(width, height)
    descriptor(pattern)
    digest = hashlib.sha256()
    vertical = pattern.startswith("y-")
    cached_y = None if vertical else _bytes(array("H", (source_code(pattern, "Y", x, 0, width, height)<<6 for x in range(width))))
    cached_uv = None if vertical else _bytes(array("H", (source_code(pattern, c, x, 0, width, height)<<6
                                                        for x in range(width//2) for c in ("Cb", "Cr"))))
    with Path(path).open("xb") as handle:
        for y in range(height):
            data = cached_y if cached_y is not None else (source_code(pattern, "Y", 0, y, width, height)<<6).to_bytes(2, "little")*width
            handle.write(data)
            digest.update(data)
        for y in range(height//2):
            data = cached_uv if cached_uv is not None else b"".join((source_code(pattern, c, 0, y, width, height)<<6).to_bytes(2, "little")
                                                                   for c in ("Cb", "Cr"))*(width//2)
            handle.write(data)
            digest.update(data)
    return {"file": Path(path).name, "bytes": width*height*3, "sha256": digest.hexdigest()}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while data := handle.read(1<<20): digest.update(data)
    return digest.hexdigest()


def _empty():
    return {"samples": 0, "different": 0, "sum_signed_error": 0,
            "sum_absolute_error": 0, "maximum_absolute_error": 0}


def _add(state, error):
    state["samples"] += 1
    state["different"] += int(error != 0)
    state["sum_signed_error"] += error
    state["sum_absolute_error"] += abs(error)
    state["maximum_absolute_error"] = max(state["maximum_absolute_error"], abs(error))


def _finish(state):
    count = state["samples"]
    return dict(state, mean_signed_error=state["sum_signed_error"]/count if count else None,
                mean_absolute_error=state["sum_absolute_error"]/count if count else None,
                maximum_absolute_error=state["maximum_absolute_error"] if count else None)


def scan(path, pattern, width=1920, height=1080, scale=2):
    """Validate EVERY downloaded word; retain only row-sized working buffers."""
    dimensions(width, height)
    descriptor(pattern)
    if scale not in (1, 2): raise ValueError("unsupported scale")
    ow, oh = width*scale, height*scale
    digest, luma = hashlib.sha256(), hashlib.sha256()
    states = {c: {"all": _empty(), "rows": [_empty(), _empty()], "columns": [_empty(), _empty()],
                  "full_code_samples": 0, "minimum_code": 1023, "maximum_code": 0,
                  "constant_codes_preserved": True} for c in CHANNELS}
    predictions = {}
    if pattern != "channel-tags":
        prediction_axis = descriptor(pattern)[0]
        for c in CHANNELS:
            extent = (ow if prediction_axis == "x" else oh)//(1 if c == "Y" else 2)
            predictions[c] = array("i", (expected_code(pattern, c, m if prediction_axis == "x" else 0,
                                                       m if prediction_axis == "y" else 0, width, height, scale)
                                         for m in range(extent)))
    with Path(path).open("rb") as handle:
        for chroma, count in ((False, oh), (True, oh//2)):
            for y in range(count):
                data = handle.read(ow*2)
                if len(data) != ow*2: raise ValueError("truncated P010 frame")
                digest.update(data)
                if not chroma: luma.update(data)
                words = array("H")
                words.frombytes(data)
                if sys.byteorder != "little": words.byteswap()
                components = ("Cb", "Cr") if chroma else ("Y",)
                cw, ch = (ow//2, oh//2) if chroma else (ow, oh)
                for component_index, c in enumerate(components):
                    state = states[c]
                    if pattern != "channel-tags":
                        axis, _, _ = descriptor(pattern)
                        start, length, _, _ = band(pattern, c, width, height)
                        low, high = scale*start+16, scale*(start+length)-16
                    for x in range(cw):
                        word = words[x*2+component_index] if chroma else words[x]
                        if word & 63: raise ValueError("P010 unused low bits nonzero")
                        code = word>>6
                        state["full_code_samples"] += 1
                        state["minimum_code"] = min(state["minimum_code"], code)
                        state["maximum_code"] = max(state["maximum_code"], code)
                        if pattern == "channel-tags":
                            state["constant_codes_preserved"] &= code == TAGS[c]
                            interior = 16 <= x < cw-16 and 16 <= y < ch-16
                        elif axis == "x":
                            interior = low <= x < high and 16 <= y < ch-16
                        else:
                            interior = low <= y < high and 16 <= x < cw-16
                        if interior:
                            expected = TAGS[c] if pattern == "channel-tags" else predictions[c][x if axis == "x" else y]
                            error = code-expected
                            _add(state["all"], error)
                            _add(state["rows"][y%2], error)
                            _add(state["columns"][x%2], error)
        if handle.read(1): raise ValueError("P010 trailing bytes/stride padding")
    channels = {}
    for c, state in states.items():
        channels[c] = dict(_finish(state["all"]),
                           row_parity={str(p): _finish(state["rows"][p]) for p in (0, 1)},
                           column_parity={str(p): _finish(state["columns"][p]) for p in (0, 1)},
                           full_code_samples=state["full_code_samples"], minimum_code=state["minimum_code"],
                           maximum_code=state["maximum_code"],
                           constant_codes_preserved=state["constant_codes_preserved"] if pattern == "channel-tags" else None)
    return {"sha256": digest.hexdigest(), "luma_sha256": luma.hexdigest(), "channels": channels,
            "unused_low_bits_zero": True, "margin_output_samples": 16,
            "expectation": "axis-isolated affine-band rounded Annex B first moments, not continuous unrounded coordinates or Dolby conformance"}


def run(binary, destination, width=1920, height=1080, repeats=2, device="/dev/dri/renderD128"):
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    started = time.monotonic()
    report = {"schema": "yblod.hardware-large-scaling.v1", "status": "failed", "invocations": [],
              "results": {}, "inputs": {}, "hardware_engine_verified": False,
              "source_sha256": file_hash(__file__), "kernel": list(os.uname()),
              "siting_helper_sha256": file_hash(siting_helper.__file__),
              "transport_helper_sha256": file_hash(transport_helper.__file__),
              "interpretation": "synthetic rounded-band diagnostics; identical bytes with changed input siting reinterpret the physical grid; no fitting or certified Dolby geometry"}

    def call(pattern, size, i, o, repetition=0, copy=False):
        stem = f"{'copy' if copy else 'default'}-{i}-to-{o}-{pattern}-{size[0]}x{size[1]}-{repetition}"
        output = root/f"{stem}.p010"
        argv = [str(executable), str(device), str(root/f"{pattern}-input.p010"), str(output),
                str(width), str(height), *map(str, size), "copy" if copy else "default"]
        if not copy: argv += ["--input-chroma", i, "--output-chroma", o]
        entry = {"argv": argv, "pattern": pattern, "output_file": output.name}
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
        if output.exists(): entry["output_sha256"] = file_hash(output)
        if entry["exit_status"] != 0: raise ValueError("large probe failed/timed out")
        # The siting validator's fixed64 shape is intentionally not reused.
        value = json.loads(stdout)
        declared_input, declared_output = value.get("input_size"), value.get("output_size")
        if any(not isinstance(v, list) or len(v) != 2 or any(type(n) is not int for n in v)
               for v in (declared_input, declared_output)):
            raise ValueError("large invocation dimension types invalid")
        value["input_size"], value["output_size"] = [64, 64], [64, 64]
        validate_invocation(json.dumps(value), 64, i, o, copy)
        if declared_input != [width, height] or declared_output != list(size):
            raise ValueError("large invocation dimensions differ from request")
        value["input_size"], value["output_size"] = declared_input, declared_output
        entry["invocation"] = value
        return output, entry

    try:
        dimensions(width, height)
        if type(repeats) is not int or not 2 <= repeats <= 4: raise ValueError("2..4 repeats required")
        executable = Path(binary).resolve()
        report.update(binary=str(executable), binary_sha256=file_hash(executable),
                      input_size=[width, height], output_size=[width*2, height*2], repeats=repeats)
        for pattern in PATTERNS:
            report["inputs"][pattern] = generate(root/f"{pattern}-input.p010", pattern, width, height)
            path, entry = call(pattern, (width, height), "left", "left", copy=True)
            entry["scan"] = scan(path, pattern, width, height, 1)
            entry["identity_exact"] = entry["scan"]["sha256"] == report["inputs"][pattern]["sha256"]
            if not entry["identity_exact"]: raise ValueError("copy identity failed")
        report["copy_checks_complete"] = True
        luma_baselines, score_cache = {}, {}
        for scale in (1, 2):
            size = width*scale, height*scale
            for i, o in CONFIGURATIONS:
                config = report["results"].setdefault(f"{i}-to-{o}", {})
                cases = config.setdefault(str(scale), {})
                for pattern in PATTERNS:
                    paths = [call(pattern, size, i, o, n)[0] for n in range(1 if scale == 1 else repeats)]
                    hashes = [file_hash(path) for path in paths]
                    if len(set(hashes)) != 1: raise ValueError("repeated large output differs")
                    key = (pattern, scale, hashes[0])
                    if key not in score_cache: score_cache[key] = scan(paths[0], pattern, width, height, scale)
                    result = dict(score_cache[key], repeat_sha256=hashes, repeat_stable=True,
                                  identity_exact=hashes[0] == report["inputs"][pattern]["sha256"] if scale == 1 else None)
                    cases[pattern] = result
                    if scale == 2 and any(c["samples"] == 0 for c in result["channels"].values()):
                        raise ValueError("large 2x scored interior must be nonempty in every component")
                    if scale == 1 and i == o and not result["identity_exact"]:
                        raise ValueError("same-grid large 1:1 identity failed")
                    if pattern == "channel-tags" and not all(c["constant_codes_preserved"] for c in result["channels"].values()):
                        raise ValueError("large constant/channel tags changed")
                    baseline = luma_baselines.setdefault((pattern, scale), result["luma_sha256"])
                    result["luma_identical_across_siting_requests"] = baseline == result["luma_sha256"]
                    if not result["luma_identical_across_siting_requests"]: raise ValueError("large luma changed across siting requests")
        report["status"] = "complete"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report["resources"] = {"elapsed_seconds": time.monotonic()-started, "self_peak_rss_native": usage.ru_maxrss,
                           "rss_native_unit": "bytes" if sys.platform == "darwin" else "KiB",
                           "interpretation": "Python process lifetime RSS only; elapsed includes CPU scans, not playback"}
    with (root/"large-scaling-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("generate", "scan", "run"):
        item = sub.add_parser(action)
        if action == "run": item.add_argument("binary", type=Path)
        item.add_argument("path", type=Path)
        item.add_argument("--width", type=int, default=1920)
        item.add_argument("--height", type=int, default=1080)
        if action != "run": item.add_argument("--pattern", required=True)
        if action == "scan": item.add_argument("--scale", type=int, choices=(1, 2), default=2)
        if action == "run":
            item.add_argument("--device", default="/dev/dri/renderD128")
            item.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.action == "generate": result = generate(args.path, args.pattern, args.width, args.height)
    elif args.action == "scan": result = scan(args.path, args.pattern, args.width, args.height, args.scale)
    else: result = run(args.binary, args.path, args.width, args.height, args.repeats, args.device)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.action == "run": raise SystemExit(result["status"] != "complete")
