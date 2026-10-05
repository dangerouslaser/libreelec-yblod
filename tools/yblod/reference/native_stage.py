#!/usr/bin/env python3
"""Bounded ctypes bridge to the integer C stages; Python remains the oracle.

One native call processes a chunk. Missing BL planes are explicit zero arrays
(including the unused luma Cb/Cr planes); an MMR guide is never inferred.
Only whole native codes are accepted: no fractional transport policy is chosen.
Build hashes detect accidental artifact/source mismatch, not malicious binaries.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import stat

from base_mapping_stage import BaseMappingConfig
from nlq_stage import NLQConfig

ROOT = Path(__file__).resolve().parent
LIMIT = 65536
SCHEMA = "yblod.native-stage-build.v1"


class Segment(C.Structure):
    _fields_ = [("method", C.c_int32), ("order", C.c_int32),
                ("constant", C.c_int64), ("coefficients", (C.c_int64*7)*3)]


class Component(C.Structure):
    _fields_ = [("pivot_count", C.c_int32), ("pivots", C.c_int32*17),
                ("segments", Segment*16)]


class Mapping(C.Structure):
    _fields_ = [("bit_depth", C.c_int32), ("denominator", C.c_int32),
                ("components", Component*3)]


class NLQ(C.Structure):
    _fields_ = [("bit_depth", C.c_int32), ("denominator", C.c_int32),
                ("offset", C.c_int32), ("slope", C.c_uint64),
                ("threshold", C.c_uint64), ("maximum", C.c_uint64)]


def digest(path):
    h = hashlib.sha256()
    path = Path(path)
    with _regular(path) as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
        _unchanged(path, before, os.fstat(stream.fileno()))
    return h.hexdigest()


def _regular(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("regular file required: " + str(path))
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _unchanged(path, before, after):
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    stamp = lambda value: tuple(getattr(value, field) for field in fields)
    if stamp(before) != stamp(after) or stamp(before) != stamp(Path(path).stat()):
        raise ValueError("file changed while reading: " + str(path))


def _record(path):
    with _regular(path) as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(1024*1024+1)
        if len(raw) > 1024*1024:
            raise ValueError("build record exceeds 1 MiB")
        _unchanged(path, before, os.fstat(stream.fileno()))
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate build record key")
            result[key] = value
        return result
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite build record value")
        return result
    record = json.loads(raw, object_pairs_hook=pairs, parse_float=number,
                        parse_constant=number)
    if type(record) is not dict:
        raise ValueError("build record must be an object")
    return raw, record


def source_hashes():
    return {name: digest(ROOT/name) for name in (
        "native_composer.c", "native_composer.h", "native_stage.py",
        "base_mapping_stage.py", "nlq_stage.py")}


def build(destination, *, compiler="cc"):
    """Compile into a fresh directory; publish build.json only after success."""
    destination = Path(destination).resolve()
    destination.mkdir()
    library = destination/"libnative_composer.so"
    before = source_hashes()
    command = [compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall",
               "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
               str(ROOT/"native_composer.c"), "-o", str(library)]
    version = subprocess.run([compiler, "--version"], capture_output=True,
                             text=True, check=True).stdout
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("native compilation failed: " + result.stderr)
    if source_hashes() != before:
        raise ValueError("native source changed during compilation")
    record = {"schema": SCHEMA, "status": "complete", "abi_version": 1,
              "library": library.name, "library_sha256": digest(library),
              "source_sha256": before, "command": command,
              "compiler_version": version, "platform": platform.platform()}
    with (destination/"build.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return library


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: expected integer in [{low}, {high}]")
    return value


def _mapping(config):
    if type(config) is not BaseMappingConfig:
        raise ValueError("BaseMappingConfig required")
    checked = BaseMappingConfig(config.bit_depth, config.denominator, config.mappings)
    encoded = Mapping(checked.bit_depth, checked.denominator)
    for output, mapping in zip(encoded.components, checked.mappings):
        output.pivot_count = len(mapping.pivots)
        for index, pivot in enumerate(mapping.pivots):
            output.pivots[index] = pivot
        for target, segment in zip(output.segments, mapping.segments):
            if segment.method == "polynomial":
                target.method, target.order = 0, len(segment.coefficients)-1
                for index, value in enumerate(segment.coefficients):
                    target.coefficients[0][index] = value
            else:
                target.method, target.order = 1, len(segment.coefficients)
                target.constant = segment.constant
                for row, values in enumerate(segment.coefficients):
                    for column, value in enumerate(values):
                        target.coefficients[row][column] = value
    return checked, encoded


def _nlq(config):
    if type(config) is not NLQConfig:
        raise ValueError("NLQConfig required")
    values = [getattr(config, name) for name, _ in NLQ._fields_]
    checked = NLQConfig(*values)
    return checked, NLQ(*values)


def _bounded(values, name):
    """Reject oversized iterators after at most LIMIT+1 elements."""
    result = []
    for value in values:
        if len(result) == LIMIT:
            raise ValueError(f"{name}: chunk exceeds {LIMIT}")
        result.append(value)
    return result


class NativeStage:
    def __init__(self, library_path, mapping_config, nlq_configs, output_depth,
                 *, disabled=False):
        if type(disabled) is not bool:
            raise ValueError("disabled must be boolean")
        if type(output_depth) is not int or output_depth not in (10, 12):
            raise ValueError("output_depth must be integer 10 or 12")
        self._mapping_python, self._mapping = _mapping(mapping_config)
        self._nlq_python, self._nlq = [], []
        if disabled:
            if nlq_configs is not None:
                raise ValueError("disabled EL requires no NLQ configurations")
        else:
            if type(nlq_configs) not in (list, tuple) or len(nlq_configs) != 3:
                raise ValueError("three NLQ configurations required")
            for config in nlq_configs:
                checked, encoded = _nlq(config)
                if checked.denominator != self._mapping_python.denominator:
                    raise ValueError("mapping and NLQ denominator mismatch")
                self._nlq_python.append(checked)
                self._nlq.append(encoded)
        self._disabled, self._output_depth = disabled, output_depth
        library = Path(library_path).resolve()
        record_path = library.parent/"build.json"
        raw, record = _record(record_path)
        if (record.get("schema") != SCHEMA or record.get("status") != "complete"
                or type(record.get("abi_version")) is not int
                or record["abi_version"] != 1 or record.get("library") != library.name
                or record.get("source_sha256") != source_hashes()
                or record.get("library_sha256") != digest(library)):
            raise ValueError("native build provenance mismatch")
        self._library = C.CDLL(str(library))
        # Ordinary mutation detection, not a secure loader or immutable snapshot.
        if (digest(library) != record["library_sha256"]
                or source_hashes() != record["source_sha256"]
                or _record(record_path)[0] != raw):
            raise ValueError("native build changed during load")
        abi = self._library.yb_abi_version
        abi.argtypes, abi.restype = [], C.c_uint32
        if abi() != 1:
            raise ValueError("native ABI version mismatch")
        for name, structure in (("mapping_config", Mapping), ("nlq_config", NLQ),
                                ("component_mapping", Component), ("segment", Segment)):
            query = getattr(self._library, "yb_sizeof_"+name)
            query.argtypes, query.restype = [], C.c_uint64
            if query() != C.sizeof(structure):
                raise ValueError("native ABI structure size mismatch: "+name)
        u16, i32 = C.POINTER(C.c_uint16), C.POINTER(C.c_int32)
        self._process = self._library.yb_process_chunk
        self._process.argtypes = [C.POINTER(Mapping), C.POINTER(NLQ), C.c_int32,
                                  u16, u16, u16, u16, C.c_uint32, C.c_int32,
                                  C.c_int32, u16, i32, i32, u16]
        self._process.restype = C.c_int
        self.provenance = {"backend": "native-c-integer", "abi_version": 1,
                           "library_sha256": record["library_sha256"],
                           "build_record_sha256": hashlib.sha256(raw).hexdigest(),
                           "source_sha256": record["source_sha256"],
                           "build_record": record,
                           "scope": "Native whole-code chunks; no fractional EL policy."}

    def process_planes(self, component, y, cb, cr, el=None):
        component = _integer(component, "component", 0, 2)
        planes = [None if p is None else _bounded(p, "BL plane") for p in (y, cb, cr)]
        present = [plane for plane in planes if plane is not None]
        if not present or not present[0]:
            raise ValueError("nonempty BL plane required")
        count = len(present[0])
        if any(len(plane) != count for plane in present):
            raise ValueError("BL plane lengths differ")
        # A missing guide is valid only where the configured mapping is polynomial.
        if any(s.method == "mmr" for s in self._mapping_python.mappings[component].segments) and any(p is None for p in planes):
            raise ValueError("MMR requires an explicit luma guide and both chroma planes")
        if (y, cb, cr)[component] is None:
            raise ValueError("driven BL component is missing")
        top = (1 << self._mapping_python.bit_depth)-1
        buffers = []
        for plane in planes:
            values = [0]*count if plane is None else plane
            for value in values:
                _integer(value, "BL sample", 0, top)
            buffers.append((C.c_uint16*count)(*values))
        if self._disabled:
            if el is not None:
                raise ValueError("disabled EL requires no enhancement samples")
            enhancement, config = None, None
        else:
            if el is None:
                raise ValueError("enhancement samples required")
            values = _bounded(el, "EL plane")
            if len(values) != count:
                raise ValueError("EL plane length differs")
            for value in values:
                _integer(value, "EL sample", 0, (1 << self._nlq_python[component].bit_depth)-1)
            enhancement = (C.c_uint16*count)(*values)
            config = C.byref(self._nlq[component])
        mapped, residual = (C.c_uint16*count)(), (C.c_int32*count)()
        summed, reconstructed = (C.c_int32*count)(), (C.c_uint16*count)()
        status = self._process(C.byref(self._mapping), config, component, *buffers,
                               enhancement, count, int(not self._disabled),
                               self._output_depth, mapped, residual, summed, reconstructed)
        if status:
            raise ValueError(f"native chunk rejected (status {status})")
        return dict(mapped=list(mapped), residual=list(residual), sum=list(summed),
                    reconstructed=list(reconstructed))

    def process(self, component, triplets, el_samples=None):
        triples = _bounded(triplets, "triplets")
        if any(type(row) not in (list, tuple) or len(row) != 3 for row in triples):
            raise ValueError("each BL triplet must contain exactly three samples")
        return self.process_planes(component, *(list(values) for values in zip(*triples)),
                                   el=el_samples) if triples else self.process_planes(component, [], [], [], el_samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="fresh build directory")
    parser.add_argument("--compiler", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    print(build(args.destination, compiler=args.compiler))


if __name__ == "__main__":
    main()
