"""Bounded synthetic texture observer; float models are not GPU/Dolby oracles."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import time

SCHEMA = "yblod.native-texture-probe.v1"
SOURCES = ("native_texture_probe.c", "native_texture_fixture.h", "native_texture_probe.comp", "native_texture_probe.py")
FIELDS = ("fetched_unorm", "sampled_unorm", "scaled_el", "centered", "guard_magnitude", "guarded", "nlq_residual")


def f32(value):
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def floating(word):
    if type(word) is not int or not 0 <= word <= 0xffffffff:
        raise ValueError("uint32 bit pattern required")
    return struct.unpack("<f", struct.pack("<I", word))[0]


def fixture():
    words = (0, 32704, 32752, 32767, 32768, 32769, 32784, 65535)
    pixels = []
    for row in range(2):
        for column in range(8):
            y = words[column] if row == 0 else 65535 - words[column]
            if (column, row) == (0, 1):
                y = 32832
            pixels.extend((words[(column + 2 * row) % 8], y, words[7 - column],
                           65535 if (column + row) % 2 else 0))
    positions = ([(4*x, 4*y) for y in range(2) for x in range(8)]
                 + [(4*x+2, 4*y) for y in range(2) for x in range(8)]
                 + [(4*x+1, 0) for x in range(8)] + [(4*x, 2) for x in range(8)]
                 + [(-4, 0), (-2, 0), (32, 0), (34, 0), (0, -4), (0, -2), (0, 8), (0, 10)])
    queries = [[x, y, mode, min(1, max(0, y//4))*8 + min(7, max(0, x//4))]
               for x, y in positions for mode in (0, 1)]
    return dict(width=8, height=2, count=112, record_words=36,
                pixels_u16=pixels, queries_i32=queries,
                parameters_u32=[112, bits(f32(f32(1/64)*(65535/1023))),
                                bits(f32(f32(Fraction(1, 1023))*512)),
                                bits(f32(Fraction(1023*2048, 8388608))), bits(f32(Fraction(-1024, 8388608)))])


def same(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is list:
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(same(actual[k], v) for k, v in expected.items())
    return actual == expected


def validate_fixture(report):
    expected = fixture()
    if type(report) is not dict or report.get("schema") != SCHEMA or any(not same(report.get(k), v) for k, v in expected.items()):
        raise ValueError("fixed synthetic fixture/layout mismatch")
    return expected


def raw_sample(pixels, query, component):
    """Exact ideal rational; no finite-precision GPU sampling assertion."""
    x, y, mode, _ = query
    def at(ix, iy):
        return pixels[4*(min(1, max(0, iy))*8 + min(7, max(0, ix))) + component]
    if mode == 0:
        return Fraction(at((x+2)//4, (y+2)//4))
    ix, iy = x//4, y//4
    tx, ty = Fraction(x % 4, 4), Fraction(y % 4, 4)
    return ((1-tx)*(1-ty)*at(ix, iy)+tx*(1-ty)*at(ix+1, iy)
            +(1-tx)*ty*at(ix, iy+1)+tx*ty*at(ix+1, iy+1))


def sequential_model(pixels, query, component, parameters):
    """One declared float32 operation order, not a GPU bit-exact prediction."""
    x, y, mode, point = query
    def at(ix, iy):
        return f32(Fraction(pixels[4*(min(1, max(0, iy))*8+min(7, max(0, ix)))+component], 65535))
    fetched = f32(Fraction(pixels[4*point+component], 65535))
    if mode == 0:
        sampled = at((x+2)//4, (y+2)//4)
    else:
        ix, iy = x//4, y//4
        tx, ty = (x % 4)/4, (y % 4)/4
        low = f32(f32((1-tx)*at(ix, iy)) + f32(tx*at(ix+1, iy)))
        high = f32(f32((1-tx)*at(ix, iy+1)) + f32(tx*at(ix+1, iy+1)))
        sampled = f32(f32((1-ty)*low) + f32(ty*high))
    scale, offset, slope, threshold = map(floating, parameters[1:])
    scaled = f32(sampled*scale)
    if component == 3:
        return [fetched, sampled, scaled, 0., 0., 0., 0.], 0
    centered = f32(scaled-offset)
    noise = f32(2**-22 * max(abs(scaled), abs(offset)))
    guard = int(abs(centered) <= noise)
    cleaned = 0. if guard else centered
    sign = -1 if cleaned < 0 else 1 if cleaned > 0 else 0
    residual = f32(sign*f32(f32(abs(cleaned)*slope)+threshold))
    return [fetched, sampled, scaled, centered, noise, cleaned, residual], guard


def ordered(word):
    return 0x80000000-(word & 0x7fffffff) if word & 0x80000000 else word+0x80000000


def analyse(report):
    expected = validate_fixture(report)
    required = dict(status="observed", gpu_attempted=True, device_binding_verified=True,
        cleanup_succeeded=True, observed_gl_error=0, observed_egl_error=12288,
        integer_control_mismatches=0, nonfinite_values=0, endpoint_mismatches=0,
        invalid_guard_flags=0, invalid_zero_controls=0)
    if any(not same(report.get(k), v) for k, v in required.items()):
        raise ValueError("texture observation hard gate failed")
    if type(report.get("fence_wait_result")) is not int or report["fence_wait_result"] not in (37146, 37148):
        raise ValueError("finite completion fence failed")
    if not same(report.get("format_caps"), dict(rgba16_supported=1, rgba16ui_supported=1, filter=33463)):
        raise ValueError("required texture/filter capabilities missing")
    records = report.get("records_u32")
    if type(records) is not list or len(records) != 112:
        raise ValueError("exact112 observation records required")
    metrics = {name: dict(compared=0, bit_differences=0, max_ulp_difference=0, max_absolute_difference=0.) for name in FIELDS}
    ideal_error = {"sampled_unorm_max_raw_word_equivalent": 0., "scaled_el_max_native_code_equivalent": 0.}
    branch_differences = 0
    for query, record in zip(expected["queries_i32"], records):
        if type(record) is not list or len(record) != 36 or any(type(w) is not int or not 0 <= w <= 0xffffffff for w in record):
            raise ValueError("exact36 uint32 words required per record")
        point = query[3]
        if record[:4] != expected["pixels_u16"][4*point:4*point+4]:
            raise ValueError("integer texture control mismatch")
        for component in range(4):
            models, flag = sequential_model(expected["pixels_u16"], query, component, expected["parameters_u32"])
            values = [floating(record[4+4*k+component]) for k in range(7)]
            if not all(map(math.isfinite, values)):
                raise ValueError("nonfinite texture observation")
            raw_point = expected["pixels_u16"][4*point+component]
            if raw_point in (0, 65535) and record[4+component] != bits(raw_point/65535):
                raise ValueError("normalization endpoint mismatch")
            actual_flag = record[32+component]
            if actual_flag not in ((0,) if component == 3 else (0, 1)):
                raise ValueError("invalid guard flag")
            if component < 3 and (actual_flag != int(abs(values[3]) <= values[4])
                    or record[24+component] != (0 if actual_flag else record[16+component])):
                raise ValueError("reported guard branch inconsistent with observed inputs")
            if component == 3 and any(record[offset+3] & 0x7fffffff for offset in (16, 20, 24, 28)):
                raise ValueError("non-colour alpha arithmetic lanes must be zero")
            if values[5] == 0 and record[28+component] & 0x7fffffff:
                raise ValueError("zero guarded input must produce signed zero residual")
            branch_differences += actual_flag != flag
            for index, name in enumerate(FIELDS):
                value, model = values[index], models[index]
                actual_bits, model_bits = record[4+4*index+component], bits(model)
                m = metrics[name]; m["compared"] += 1
                m["bit_differences"] += actual_bits != model_bits
                m["max_ulp_difference"] = max(m["max_ulp_difference"], abs(ordered(actual_bits)-ordered(model_bits)))
                m["max_absolute_difference"] = max(m["max_absolute_difference"], abs(value-model))
            raw = raw_sample(expected["pixels_u16"], query, component)
            ideal_error["sampled_unorm_max_raw_word_equivalent"] = max(ideal_error["sampled_unorm_max_raw_word_equivalent"], abs(values[1]*65535-float(raw)))
            ideal_error["scaled_el_max_native_code_equivalent"] = max(ideal_error["scaled_el_max_native_code_equivalent"], abs(values[2]*1023-float(raw/64)))
    return dict(sequential_binary32_comparison=metrics, guard_branch_differences=branch_differences,
                ideal_rational_comparison=ideal_error,
                interpretation="Recorded differences are observations, not pass/fail ULP thresholds, GPU conformance or licensed fractional-NLQ rules.")


def digest(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode) or not 0 < initial.st_size <= 8*1024**2:
            raise ValueError("bounded regular artifact required")
        value = hashlib.sha256(); count = 0
        while block := stream.read(65536):
            count += len(block)
            if count > 8*1024**2: raise ValueError("artifact grew")
            value.update(block)
        def snap(info): return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        if count != initial.st_size or snap(os.fstat(stream.fileno())) != snap(initial) or snap(path.stat()) != snap(initial):
            raise ValueError("artifact changed")
    return value.hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def reject(value): raise ValueError("nonfinite JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def memory():
    try:
        path = next(x.split(":", 2)[2] for x in Path("/proc/self/cgroup").read_text().splitlines() if x.startswith("0::"))
        root = Path("/sys/fs/cgroup") / path.lstrip("/")
        return {name: (root / name).read_text().strip() for name in
                ("memory.max", "memory.swap.max", "memory.swap.current", "memory.peak", "memory.events")}
    except (OSError, StopIteration):
        return {}


def run(binary, shader, destination, *, device="/dev/dri/renderD128", validate_only=False, require_memory_cap=True):
    if type(validate_only) is not bool or type(require_memory_cap) is not bool:
        raise ValueError("strict boolean controls required")
    if not re.fullmatch(r"/dev/dri/renderD[0-9]+", device) or not 128 <= int(device.split("renderD")[1]) <= 1048575:
        raise ValueError("explicit render node required")
    before = memory()
    if require_memory_cap and not (before.get("memory.swap.max") == "0"
            and before.get("memory.max", "").isdigit() and 0 < int(before["memory.max"]) <= 512*1024**2):
        raise ValueError("requires512MiB maximum and zero job swap")
    binary, shader = Path(binary).resolve(strict=True), Path(shader).resolve(strict=True)
    here = Path(__file__).resolve().parent
    pins = {name: digest(here/name) for name in SOURCES}
    binary_pin, shader_pin = digest(binary), digest(shader)
    if shader_pin != pins["native_texture_probe.comp"] or not os.access(binary, os.X_OK):
        raise ValueError("reviewed shader and executable required")
    root = Path(destination).resolve(); root.mkdir(exist_ok=False)
    report = dict(schema="yblod.native-texture-run.v1", status="failed", source_sha256=pins,
                  binary_sha256=binary_pin, shader_sha256=shader_pin, requested_render_node=device,
                  memory_before=before, gpu_attempted=False)
    def unchanged():
        if digest(binary) != binary_pin or digest(shader) != shader_pin or any(digest(here/n) != p for n, p in pins.items()):
            raise ValueError("source/binary/shader changed")
    def invoke(args, phase):
        unchanged()
        path = root/(phase+".stdout.json")
        with path.open("xb") as stdout, (root/(phase+".stderr.log")).open("xb") as stderr:
            result = subprocess.run(args, stdout=stdout, stderr=stderr, timeout=30, check=False)
        unchanged(); pin = digest(path)
        with path.open("rb") as stream: raw = stream.read(8*1024**2+1)
        if len(raw) > 8*1024**2 or hashlib.sha256(raw).hexdigest() != pin:
            raise ValueError("report changed or oversized")
        value = strict_json(raw)
        report[phase] = dict(exit_status=result.returncode, stdout_sha256=pin, result=value)
        if result.returncode != 0: raise ValueError("native observation failed")
        return value
    start = time.monotonic()
    try:
        cpu = invoke([str(binary), "--validate"], "validation")
        validate_fixture(cpu)
        if cpu.get("status") != "validated" or cpu.get("gpu_attempted") is not False:
            raise ValueError("host validation state mismatch")
        if not validate_only:
            report["gpu_attempted"] = True
            observed = invoke([str(binary), device, str(shader)], "gpu")
            report["analysis"] = analyse(observed)
        unchanged()
        after = memory(); report["memory_after"] = after
        if require_memory_cap:
            def events(snapshot): return dict(line.split() for line in snapshot["memory.events"].splitlines())
            if (after.get("memory.max") != before.get("memory.max") or after.get("memory.swap.max") != "0"
                    or after.get("memory.swap.current") != "0"
                    or any(events(after).get(k) != events(before).get(k) for k in ("max", "oom", "oom_kill"))):
                raise ValueError("memory/swap guard changed or pressure event occurred")
        report["status"] = "validated" if validate_only else "observed"
    except Exception as error:
        report["error"] = dict(type=type(error).__name__, message=str(error))
    report["elapsed_seconds"] = time.monotonic()-start
    with (root/"report.json").open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False); stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "shader", "destination"): parser.add_argument(name)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    parser.add_argument("--validate-only", action="store_true")
    result = run(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"], "gpu_attempted": result["gpu_attempted"]}))
    raise SystemExit(result["status"] not in ("validated", "observed"))
