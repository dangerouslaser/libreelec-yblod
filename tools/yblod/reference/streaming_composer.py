#!/usr/bin/env python3
"""Bounded prepared-frame reconstruction using standalone integer stages.

Global manifest/identity validation is deliberately shared with reference.py;
its mapping, NLQ and reconstruction implementations are not called. Input is
already prepared planar420 native codes, not raw Y416 or unregistered layers.
Failures may leave partial diagnostic files, but never a completion report.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys

import base_mapping_stage as mapping
import composition_stage as composition
import nlq_stage as nlq
import reference

CHANNELS = ("Y", "Cb", "Cr")
STAGES = (("mapped", "u16le"), ("residual", "i32le"),
          ("sum", "i32le"), ("reconstructed", "u16le"))


def _snapshot(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


class PlaneReader:
    """Read only fixed-size chunks; finish verifies exact EOF and file metadata."""
    def __init__(self, root, filename, count, bit_depth):
        if type(filename) is not str or not filename:
            raise ValueError("plane path must be a nonempty relative filename")
        root = Path(root).resolve()
        self.path = (root / filename).resolve()
        if Path(filename).is_absolute() or not self.path.is_relative_to(root):
            raise ValueError("plane path must stay inside the input bundle")
        descriptor = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        try:
            initial = os.fstat(descriptor)
            if not stat.S_ISREG(initial.st_mode) or initial.st_size != count * 2:
                raise ValueError(f"{filename}: expected exactly {count} u16le samples in a regular file")
            self.handle = os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        self.initial = _snapshot(initial)
        self.filename, self.count, self.depth = filename, count, bit_depth
        self.consumed = 0
        self.digest = hashlib.sha256()

    def close(self):
        self.handle.close()

    def read(self, count):
        if type(count) is not int or not 1 <= count <= 65536 or self.consumed + count > self.count:
            raise ValueError("invalid bounded plane read count")
        data = self.handle.read(count * 2)
        if len(data) != count * 2:
            raise ValueError(f"{self.filename}: truncated plane while reading")
        values = struct.unpack(f"<{count}H", data)
        if any(value >= 1 << self.depth for value in values):
            raise ValueError(f"{self.filename}: sample exceeds declared native depth")
        self.digest.update(data)
        self.consumed += count
        return values

    def finish(self):
        if self.consumed != self.count or self.handle.read(1):
            raise ValueError(f"{self.filename}: incomplete or extra plane samples")
        if _snapshot(os.fstat(self.handle.fileno())) != self.initial:
            raise ValueError(f"{self.filename}: input file changed during processing")
        if _snapshot(self.path.stat()) != self.initial:
            raise ValueError(f"{self.filename}: input path changed during processing")
        return self.digest.hexdigest()


class StageWriter:
    def __init__(self, directory, name, encoding):
        self.path = directory / f"{name}.{encoding}"
        self.handle = self.path.open("xb")
        self.encoding = encoding
        self.count, self.low, self.high = 0, None, None
        self.digest = hashlib.sha256()

    def close(self):
        self.handle.close()

    def write(self, values):
        low, high, code = (0, 65535, "H") if self.encoding == "u16le" else (-(1 << 31), (1 << 31) - 1, "i")
        if not values or len(values) > 65536:
            raise ValueError("output chunk must have 1..65536 samples")
        if any(type(value) is not int or not low <= value <= high for value in values):
            raise ValueError(f"{self.path.name}: stage value exceeds {self.encoding} storage; no truncation")
        data = struct.pack(f"<{len(values)}{code}", *values)
        if self.handle.write(data) != len(data):
            raise OSError("short stage-file write")
        self.digest.update(data)
        self.count += len(values)
        chunk_low, chunk_high = min(values), max(values)
        self.low = chunk_low if self.low is None else min(self.low, chunk_low)
        self.high = chunk_high if self.high is None else max(self.high, chunk_high)

    def finish(self, expected_count):
        if self.count != expected_count:
            raise ValueError("output stage sample count mismatch")
        return {"file": self.path.name, "samples": self.count, "minimum": self.low,
                "maximum": self.high, "sha256": self.digest.hexdigest()}


def run(manifest_path, output, *, chunk_samples=4096):
    if type(chunk_samples) is not int or not 1 <= chunk_samples <= 65536:
        raise ValueError("chunk_samples must be integer in1..65536")
    manifest_path, output = Path(manifest_path), Path(output)
    with manifest_path.open("rb") as handle:
        raw_manifest = handle.read((8 << 20) + 1)
    if len(raw_manifest) > 8 << 20:
        raise ValueError("manifest exceeds8MiB bounded metadata allowance")
    manifest = json.loads(raw_manifest)
    reference.validate(manifest)
    metadata = manifest["metadata"]
    enabled = not metadata["disable_residual"]
    for layer in ("bl", "el") if enabled else ("bl",):
        if not isinstance(manifest[layer]["planes"], dict) or set(manifest[layer]["planes"]) != set(CHANNELS):
            raise ValueError("each consumed layer needs exactly Y/Cb/Cr planes")
    map_config = mapping.BaseMappingConfig.from_mappings(
        metadata["mappings"], bit_depth=metadata["bl_bit_depth"],
        denominator=metadata["coefficient_log2_denom"])
    nlq_configs = ([nlq.NLQConfig.from_mapping(parameters, bit_depth=metadata["el_bit_depth"],
                                            denominator=metadata["coefficient_log2_denom"])
                    for parameters in metadata["nlq"]] if enabled else None)
    needs_guide = any(segment["method"] == "mmr" for curve in metadata["mappings"] for segment in curve["segments"])
    if needs_guide and not manifest.get("mmr_luma"):
        raise ValueError("MMR requires an explicitly prepared luma guide")
    count_y = manifest["width"] * manifest["height"]
    counts = (count_y, count_y // 4, count_y // 4)
    report = {
        "schema": "yblod.composer-result.v1", "status": "complete",
        "scope": "prepared-input streaming reconstruction only; not HDMI or display-referred RGB",
        "specification": reference.SPEC, "input_manifest": manifest,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "implementation_sha256": _file_hash(__file__),
        "helper_sha256": {Path(module.__file__).name: _file_hash(module.__file__)
                          for module in (mapping, nlq, composition, reference)},
        "validation_basis": "reference.validate supplies global manifest/identity validation; arithmetic uses separate stage modules",
        "input_validation_scope": "only consumed planes: disabled EL and unused guide are not opened or hashed",
        "input_change_check": "descriptor and resolved-path size/inode/mtime/ctime before/after; not an immutable or adversarial snapshot guarantee",
        "chunk_samples": chunk_samples, "input_sha256": {}, "stages": {},
    }
    with ExitStack() as resources:
        readers = []
        def reader(filename, count, depth):
            value = PlaneReader(manifest_path.parent, filename, count, depth)
            resources.callback(value.close)
            readers.append(value)
            return value
        bl = [reader(manifest["bl"]["planes"][channel], count, metadata["bl_bit_depth"])
              for channel, count in zip(CHANNELS, counts)]
        el = ([reader(manifest["el"]["planes"][channel], count, metadata["el_bit_depth"])
               for channel, count in zip(CHANNELS, counts)] if enabled else None)
        guide = reader(manifest["mmr_luma"], counts[1], metadata["bl_bit_depth"]) if needs_guide else None
        output.mkdir(parents=False, exist_ok=False)
        writers = {}
        for channel in CHANNELS:
            for stage, encoding in STAGES:
                name = f"{stage}_{channel}"
                writers[name] = StageWriter(output, name, encoding)
                resources.callback(writers[name].close)

        for components, count in (((0,), counts[0]), ((1, 2), counts[1])):
            for start in range(0, count, chunk_samples):
                size = min(chunk_samples, count - start)
                base = {component: bl[component].read(size) for component in components}
                enhancement = ({component: el[component].read(size) for component in components} if enabled else None)
                luma = guide.read(size) if components == (1, 2) and guide is not None else None
                for component in components:
                    stages = {name: [] for name, _ in STAGES}
                    for index in range(size):
                        samples = ((base[0][index], 0, 0) if component == 0 else
                                   (luma[index] if luma is not None else 0, base[1][index], base[2][index]))
                        mapped = mapping.map_sample(component, samples, map_config)
                        residual = nlq.correction(enhancement[component][index], nlq_configs[component]) if enabled else 0
                        stages["mapped"].append(mapped)
                        stages["residual"].append(residual)
                        stages["sum"].append(mapped + residual)
                        stages["reconstructed"].append(composition.compose_residual(mapped, residual, metadata["output_bit_depth"]))
                    for name, _ in STAGES:
                        writers[f"{name}_{CHANNELS[component]}"].write(stages[name])
        for source in readers:
            digest = source.finish()
            previous = report["input_sha256"].get(source.filename)
            if previous is not None and previous != digest:
                raise ValueError("aliased input file yielded inconsistent hashes")
            report["input_sha256"][source.filename] = digest
        for channel, count in zip(CHANNELS, counts):
            for stage, _ in STAGES:
                name = f"{stage}_{channel}"
                report["stages"][name] = writers[name].finish(count)
    # Every input completed and every output stream closed successfully first.
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    pending = output / "report.pending.json"
    with pending.open("x") as handle:
        handle.write(serialized)
    # Hard link supplies no-overwrite publication of an already closed report.
    os.link(pending, output / "report.json")
    try:
        pending.unlink()
    except OSError:
        # The complete report is already published; an extra temporary hard
        # link is harmless and must not turn successful reconstruction into a
        # reported failure after completion became visible.
        pass
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--chunk-samples", type=int, default=4096)
    args = parser.parse_args()
    try:
        run(args.manifest, args.output, chunk_samples=args.chunk_samples)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"streaming composer: {error}\n")


if __name__ == "__main__":
    main()
