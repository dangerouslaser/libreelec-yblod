#!/usr/bin/env python3
"""Bounded diagnostic colour-frame output; no embedded metadata or HDMI.

Configuration is caller-supplied and hash-bound to a completed composer report.
This does not establish that source DM was parsed from a matching real RPU.
"""
import argparse
from collections import OrderedDict
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct

import colour_stage
import reference


def _json(path):
    with Path(path).open("rb") as handle:
        raw = handle.read((8 << 20) + 1)
    if len(raw) > 8 << 20:
        raise ValueError("JSON exceeds 8 MiB allowance")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _snapshot(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


class Plane:
    def __init__(self, root, record, width, height):
        name = record["file"]
        if type(name) is not str or Path(name).is_absolute():
            raise ValueError("relative stage filename required")
        self.path = (root / name).resolve()
        if not self.path.is_relative_to(root.resolve()):
            raise ValueError("stage path escapes composer output")
        descriptor = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        try:
            s = os.fstat(descriptor)
            if not stat.S_ISREG(s.st_mode) or s.st_size != width * height * 2 or record["samples"] != width * height:
                raise ValueError("stage count/size mismatch")
            self.handle = os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        try:
            self.initial = _snapshot(s)
            digest = hashlib.sha256()
            while data := self.handle.read(65536):
                if len(data) % 2 or any(v[0] > 4095 for v in struct.iter_unpack("<H", data)):
                    raise ValueError("invalid 12-bit reconstructed plane")
                digest.update(data)
            if digest.hexdigest() != record["sha256"]:
                raise ValueError("stage hash mismatch")
            self.width, self.height = width, height
            self.cache = OrderedDict()
            self.finish()
        except BaseException:
            self.handle.close()
            raise

    def row(self, index):
        index = min(self.height - 1, max(0, index))
        if index not in self.cache:
            self.handle.seek(index * self.width * 2)
            raw = self.handle.read(self.width * 2)
            if len(raw) != self.width * 2:
                raise ValueError("plane truncated during row processing")
            values = struct.unpack(f"<{self.width}H", raw)
            if any(v > 4095 for v in values):
                raise ValueError("plane changed to invalid native codes")
            self.cache[index] = values
            while len(self.cache) > 2:
                self.cache.popitem(last=False)
        return self.cache[index]

    def finish(self):
        if _snapshot(os.fstat(self.handle.fileno())) != self.initial or _snapshot(self.path.stat()) != self.initial:
            raise ValueError("input stage changed during conversion")

    def close(self):
        self.handle.close()


def _expand(first, second, fy, x):
    ix, fx = x // 2, (x % 2) / 2
    following = min(ix + 1, len(first) - 1)
    a = first[ix] * (1 - fy) + second[ix] * fy
    b = first[following] * (1 - fy) + second[following] * fy
    return a * (1 - fx) + b * fx


def run(result, configuration, output):
    result, configuration, output = Path(result).resolve(), Path(configuration), Path(output)
    composer, report_hash = _json(result / "report.json")
    settings, settings_hash = _json(configuration)
    if composer["schema"] != "yblod.composer-result.v1" or composer["status"] != "complete":
        raise ValueError("completed composer report required")
    if settings.get("schema") != "yblod.colour-frame-config.v1" or settings.get("composer_report_sha256") != report_hash:
        raise ValueError("configuration must be bound to this composer report")
    manifest = composer["input_manifest"]
    reference.validate(manifest)
    if (manifest["metadata"]["output_bit_depth"] != 12 or manifest["format"] != "yuv420p-u16le-lsb"
            or manifest["transfer"] != "pq" or manifest["chroma_location"] != "left"):
        raise ValueError("12-bit prepared PQ 420-left composer output required")
    if settings.get("chroma_expansion") != "bilinear-left-diagnostic":
        raise ValueError("explicit supported diagnostic chroma expansion required")
    cfg = colour_stage.ColourConfig.from_dm(settings["source_dm"],
        target_ycc=settings["target_ycc"], target_lms=settings["target_lms"],
        target_offset=settings["target_offset"], pq_policy=settings["pq_policy"], code_scale=settings["code_scale"])
    width, height = manifest["width"], manifest["height"]
    rectangle = settings["active_rectangle"]
    if (type(rectangle) is not list or len(rectangle) != 4 or any(type(v) is not int for v in rectangle)):
        raise ValueError("explicit integer active rectangle required")
    left, top, right, bottom = rectangle
    if not (0 <= left < right <= width and 0 <= top < bottom <= height) or left % 2 or right % 2:
        raise ValueError("invalid active rectangle or unpaired horizontal boundary")
    outside = settings["outside_codes"]
    if type(outside) is not list or len(outside) != 3 or any(type(v) is not int or not 0 <= v <= 4095 for v in outside):
        raise ValueError("explicit outside-area 12-bit codes required")
    ranges = {name: {"minimum": None, "maximum": None, "below_zero": 0, "above_one": 0}
              for name in ("source_nonlinear", "common_linear_lms", "target_linear", "transport_before_quantization")}
    stages = {}
    with ExitStack() as resources:
        planes = []
        for channel, divisor in (("Y", 1), ("Cb", 2), ("Cr", 2)):
            plane = Plane(result, composer["stages"][f"reconstructed_{channel}"], width // divisor, height // divisor)
            resources.callback(plane.close)
            planes.append(plane)
        output.mkdir(parents=False, exist_ok=False)
        files = {}
        digests = {}
        for name in ("transport_ipt444.u16le", "unembedded_tunnel.rgb8"):
            files[name] = resources.enter_context((output / name).open("xb"))
            digests[name] = hashlib.sha256()
        for y in range(height):
            luma = planes[0].row(y)
            coordinate = (y - .5) / 2
            iy = math.floor(coordinate)
            fy = coordinate - iy
            chroma = [(p.row(iy), p.row(iy + 1)) for p in planes[1:]]
            codes = []
            for x in range(width):
                converted = colour_stage.convert_sample((luma[x],
                    _expand(*chroma[0], fy, x), _expand(*chroma[1], fy, x)), cfg)
                for name, statistics in ranges.items():
                    values = getattr(converted, name)
                    low, high = min(values), max(values)
                    statistics["minimum"] = low if statistics["minimum"] is None else min(statistics["minimum"], low)
                    statistics["maximum"] = high if statistics["maximum"] is None else max(statistics["maximum"], high)
                    statistics["below_zero"] += sum(v < 0 for v in values)
                    statistics["above_one"] += sum(v > 1 for v in values)
                codes.append(converted.codes if left <= x < right and top <= y < bottom else tuple(outside))
            raw = struct.pack("<" + "H" * (width * 3), *(v for pixel in codes for v in pixel))
            packed = bytearray()
            for x, pixel in enumerate(codes):
                intensity = pixel[0]
                chroma_code = codes[x - x % 2][1 if x % 2 == 0 else 2]
                packed.extend((chroma_code >> 4, intensity >> 4, (intensity & 15) | ((chroma_code & 15) << 4)))
            for name, data in (("transport_ipt444.u16le", raw), ("unembedded_tunnel.rgb8", packed)):
                if files[name].write(data) != len(data):
                    raise OSError("short output write")
                digests[name].update(data)
        for plane in planes:
            plane.finish()
        for name, digest in digests.items():
            stages[name] = {"file": name, "sha256": digest.hexdigest(), "bytes": width * height * (6 if name.endswith("u16le") else 3)}
    report = {"schema": "yblod.colour-frame-result.v1", "status": "complete",
        "scope": "diagnostic coordinates and unembedded bytes; not playable Dolby Vision HDMI",
        "width": width, "height": height, "identity": {k: manifest["metadata"][k] for k in ("frame_id", "pts", "time_base")},
        "composer_report_sha256": report_hash, "configuration_sha256": settings_hash,
        "configuration": settings, "source_dm_association": "caller-declared, not verified against an extracted RPU",
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_sha256": {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (colour_stage, reference)},
        "processing": "one output row, two cached input rows per plane; metadata capped separately",
        "chroma_expansion": "caller-selected bilinear-left diagnostic, global row coordinates and edge replication",
        "transport_sampling": "second/third target components co-sited at even x; diagnostic byte packing only",
        "quantization": "floor(target*4096+0.5), bound 0..4095; active-area replacement afterwards",
        "input_change_check": "file metadata before/after; not an immutable snapshot guarantee",
        "statistics_scope": "all converted pixels before active-area replacement",
        "statistics": ranges, "stages": stages}
    pending = output / "output.pending.json"
    with pending.open("x") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    os.link(pending, output / "output.json")
    try:
        pending.unlink()
    except OSError:
        pass
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        run(args.result, args.configuration, args.output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"colour frame: {error}\n")
