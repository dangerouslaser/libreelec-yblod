#!/usr/bin/env python3
"""Source-pinned bounded C colour bridge, with explicit float64 policy.

This is a CPU double/libm implementation, not GPU bit-exactness or display
adaptation. Fractional reconstructed components from declared chroma expansion
are retained; this interface does not interpret fractional enhancement codes.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from colour_stage import ColourConfig, ColourResult, PQ_POLICIES, _triple
from native_stage import _bounded, _record, digest

ROOT = Path(__file__).resolve().parent
SCHEMA = "yblod.native-colour-build.v1"


class Parameters(C.Structure):
    _fields_ = [("source_ycc", C.c_double*9), ("source_offset", C.c_double*3),
                ("source_lms", C.c_double*9), ("target_ycc", C.c_double*9),
                ("target_offset", C.c_double*3), ("target_lms", C.c_double*9),
                ("pq_policy", C.c_int32), ("code_scale", C.c_int32)]


class Configuration(C.Structure):
    _fields_ = [("parameters", Parameters), ("target_ycc_inverse", C.c_double*9),
                ("target_lms_inverse", C.c_double*9), ("initialized", C.c_uint32)]


class Result(C.Structure):
    _fields_ = [("source_nonlinear", C.c_double*3), ("common_linear_lms", C.c_double*3),
                ("target_linear", C.c_double*3),
                ("transport_before_quantization", C.c_double*3), ("codes", C.c_uint16*3)]


def source_hashes():
    return {name: digest(ROOT/name) for name in (
        "native_colour.c", "native_colour.h", "native_colour_stage.py",
        "colour_stage.py", "native_stage.py", "base_mapping_stage.py", "nlq_stage.py")}


def build(destination, *, compiler="cc"):
    """Fresh source-pinned library; no fast-math, no floating contraction."""
    destination = Path(destination).resolve()
    destination.mkdir()
    library = destination/"libnative_colour.so"
    before = source_hashes()
    command = [compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra",
               "-Werror", "-Wconversion", "-Wshadow", "-fno-fast-math", "-ffp-contract=off",
               str(ROOT/"native_colour.c"), "-lm", "-o", str(library)]
    version = subprocess.run([compiler, "--version"], capture_output=True,
                             text=True, check=True).stdout
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("native colour compilation failed: " + result.stderr)
    if source_hashes() != before:
        raise ValueError("native colour source changed during compilation")
    record = {"schema": SCHEMA, "status": "complete", "abi_version": 1,
              "library": library.name, "library_sha256": digest(library),
              "source_sha256": before, "command": command,
              "compiler_version": version, "platform": platform.platform()}
    with (destination/"build.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return library


def _parameters(config):
    if type(config) is not ColourConfig:
        raise ValueError("validated ColourConfig required")
    fields = ("source_ycc", "source_offset", "source_lms", "target_ycc", "target_offset",
              "target_lms", "pq_policy", "code_scale")
    checked = ColourConfig(*(getattr(config, name) for name in fields))
    encoded = Parameters()
    for name in fields[:6]:
        values = getattr(checked, name)
        if not name.endswith("offset"):
            values = [value for row in values for value in row]
        for index, value in enumerate(values):
            getattr(encoded, name)[index] = value
    encoded.pq_policy = PQ_POLICIES.index(checked.pq_policy)
    encoded.code_scale = checked.code_scale
    return checked, encoded


class NativeColourStage:
    def __init__(self, library_path, config):
        self._python_config, parameters = _parameters(config)
        library = Path(library_path).resolve()
        record_path = library.parent/"build.json"
        raw, record = _record(record_path)
        if (record.get("schema") != SCHEMA or record.get("status") != "complete"
                or type(record.get("abi_version")) is not int or record["abi_version"] != 1
                or record.get("library") != library.name
                or record.get("source_sha256") != source_hashes()
                or record.get("library_sha256") != digest(library)):
            raise ValueError("native colour build provenance mismatch")
        self._library = C.CDLL(str(library))
        # Accidental mutation detection, not authentication or a secure loader.
        if (digest(library) != record["library_sha256"]
                or source_hashes() != record["source_sha256"]
                or _record(record_path)[0] != raw):
            raise ValueError("native colour build changed during load")
        abi = self._library.yb_colour_abi_version
        abi.argtypes, abi.restype = [], C.c_uint32
        if abi() != 1:
            raise ValueError("native colour ABI version mismatch")
        for name, structure in (("parameters", Parameters), ("config", Configuration), ("result", Result)):
            query = getattr(self._library, "yb_sizeof_colour_"+name)
            query.argtypes, query.restype = [], C.c_uint64
            if query() != C.sizeof(structure):
                raise ValueError("native colour ABI structure size mismatch: "+name)
        init = self._library.yb_colour_init
        init.argtypes, init.restype = [C.POINTER(Parameters), C.POINTER(Configuration)], C.c_int
        self._config = Configuration()
        status = init(C.byref(parameters), C.byref(self._config))
        if status:
            raise ValueError(f"native colour configuration rejected (status {status})")
        self._process = self._library.yb_colour_process_chunk
        self._process.argtypes = [C.POINTER(Configuration), C.POINTER(C.c_double), C.c_uint32,
                                  C.c_uint32, C.POINTER(Result), C.c_uint32]
        self._process.restype = C.c_int
        self.provenance = {"backend": "native-c-colour-double", "abi_version": 1,
                           "library_sha256": record["library_sha256"],
                           "build_record_sha256": hashlib.sha256(raw).hexdigest(),
                           "source_sha256": record["source_sha256"], "build_record": record,
                           "scope": "CPU double/libm colour coordinates; explicit PQ policy, not display mapping or GPU emulation."}

    def convert_chunk(self, triples):
        rows = _bounded(triples, "colour triples")
        if not rows:
            raise ValueError("colour chunk must contain 1..65536 triples")
        rows = [_triple(row) for row in rows]
        if any(not 0 <= value <= 4095 for row in rows for value in row):
            raise ValueError("reconstructed/expanded input must stay in 0..4095")
        count = len(rows)
        inputs = (C.c_double*(3*count))(*(value for row in rows for value in row))
        outputs = (Result*count)()
        status = self._process(C.byref(self._config), inputs, count, 3, outputs, 1)
        if status:
            raise ValueError(f"native colour chunk rejected (status {status})")
        return [ColourResult(*(tuple(getattr(value, name)) for name, _ in Result._fields_))
                for value in outputs]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="fresh build directory")
    parser.add_argument("--compiler", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    print(build(args.destination, compiler=args.compiler))


if __name__ == "__main__":
    main()
