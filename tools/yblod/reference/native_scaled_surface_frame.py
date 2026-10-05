"""Private P010 handoff diagnostic; never publish its report automatically.

No resampling or fractional rounding. Prepared metadata verifies association
only; actual mapping/NLQ instructions enter through the opaque decoder blob.
"""
import argparse
from contextlib import ExitStack
import ctypes as C
import hashlib
from pathlib import Path
import sys

import native_decoder_frame as bridge
import native_integration_frame as frame
import native_stage as native


class Surface(C.Structure):
    _fields_ = [("version", C.c_uint32), ("format", C.c_uint32),
                ("width", C.c_uint32), ("height", C.c_uint32),
                ("coherent_ready", C.c_uint32), ("allocation", C.POINTER(C.c_uint8)),
                ("allocation_bytes", C.c_uint64), ("y_offset", C.c_uint64),
                ("uv_offset", C.c_uint64), ("y_stride", C.c_uint64),
                ("uv_stride", C.c_uint64), ("frame_id", C.c_uint8 * 32),
                ("provenance_id", C.c_uint8 * 32)]


def source_pins():
    names = set(bridge.SOURCES) | {"native_scaled_surface.c", "native_scaled_surface.h"}
    return {name: native.digest(bridge.ROOT / name) for name in sorted(names)}


def run(args):
    if sys.byteorder != "little":
        raise ValueError("little-endian diagnostic required")
    before = frame.memory_snapshot()
    if not frame.memory_valid(before):
        raise ValueError("512MiB/zero swap scope required")
    events = dict(line.split() for line in before["memory.events"].splitlines())
    if any(events.get(key) != "0" for key in ("max", "oom", "oom_kill")):
        raise ValueError("fresh zero-event scope required")
    paths = {name: Path(getattr(args, name)).resolve(strict=True) for name in
             ("library", "instructions", "producer_report", "producer_binary", "p010")}
    pins = {name: native.digest(path) for name, path in paths.items()}
    for name, digest in pins.items():
        if digest != getattr(args, name + "_sha256"):
            raise ValueError("input identity differs")
    sources = source_pins()
    runtime_paths = [Path(sys.executable).resolve(strict=True),
                     Path("/lib/x86_64-linux-gnu/libc.so.6").resolve(strict=True),
                     Path("/lib64/ld-linux-x86-64.so.2").resolve(strict=True)]
    runtime_pins = {str(path): native.digest(path) for path in runtime_paths}
    runner_path = Path(__file__).resolve(strict=True)
    runner_sha256 = native.digest(runner_path)
    if runner_sha256 != args.runner_sha256:
        raise ValueError("runner identity differs")
    _, producer = native._record(paths["producer_report"])
    required = {"schema": "yblod.native-decoder-ingestion.v1", "status": "complete",
                "local_presentation_index": 64, "original_pts_verified": False,
                "decoder_metadata": True, "raw_rpu_exact": True,
                "el_active_planes_exact": True, "crc_requested": True,
                "warning_or_error_logs": 0, "adapter_abi": 1, "instructions_bytes": 9216}
    for key, value in required.items():
        if type(producer.get(key)) is not type(value) or producer[key] != value:
            raise ValueError("producer gate differs")
    if producer.get("instructions_sha256") != pins["instructions"]:
        raise ValueError("producer instructions differ")
    for key in ("frames_received", "packets_sent"):
        if type(producer.get(key)) is not int or not 65 <= producer[key] <= 96:
            raise ValueError("producer traversal differs")
    manifest, verified, specs, input_pins, counts, _, unchanged = frame.prepare(
        args.prepared_manifest, args.baseline, args.extraction)
    width, height = manifest["width"], manifest["height"]
    if (width, height) != (3840, 2160):
        raise ValueError("fixed frame geometry differs")
    lib = C.CDLL(str(paths["library"]))
    for name in ("yb_scaled_surface_abi_version", "yb_decoder_frame_bridge_abi_version",
                 "yb_integration_abi_version", "yb_abi_version"):
        query = getattr(lib, name); query.argtypes = []; query.restype = C.c_uint32
        if query() != 1: raise ValueError("ABI differs")
    for name, structure in (("yb_scaled_surface_sizeof_descriptor", Surface),
        ("yb_integration_sizeof_descriptor", frame.Descriptor),
        ("yb_integration_sizeof_context", frame.Context),
        ("yb_integration_sizeof_completion", frame.Completion),
        ("yb_sizeof_mapping_config", native.Mapping), ("yb_sizeof_nlq_config", native.NLQ)):
        query = getattr(lib, name); query.argtypes = []; query.restype = C.c_uint64
        if query() != C.sizeof(structure): raise ValueError("ABI size differs")
    query = lib.yb_decoder_frame_bridge_sizeof_instructions
    query.argtypes = []; query.restype = C.c_uint64
    if query() != 9216: raise ValueError("instruction ABI differs")
    reader = frame.Reader(paths["instructions"].parent, paths["instructions"].name,
                          9216, 1, pins["instructions"])
    try: raw = reader.read(9216); reader.finish()
    finally: reader.close()
    enabled = int.from_bytes(raw[4:8], "little", signed=True)
    depth = int.from_bytes(raw[8:12], "little", signed=True)
    descriptor = frame.Descriptor(1, 1, width, height, depth, enabled)
    descriptor.frame_id[:] = hashlib.sha256(str(verified["identity"]).encode()).digest()
    descriptor.provenance_id[:] = hashlib.sha256(raw).digest()
    context = frame.Context(); blob = C.create_string_buffer(raw)
    init = lib.yb_decoder_frame_bridge_init
    init.argtypes = [C.POINTER(frame.Context), C.POINTER(frame.Descriptor), C.c_void_p, C.c_size_t]
    init.restype = C.c_int
    if init(C.byref(context), C.byref(descriptor), blob, len(raw)):
        raise ValueError("instructions rejected")
    if enabled != 1 or context.mapping.bit_depth != 10 or any(n.bit_depth != 10 for n in context.nlq):
        raise ValueError("native10 enhancement route required")
    if manifest["metadata"]["bl_bit_depth"] != 10:
        raise ValueError("prepared BL declaration differs")
    needs_guide = any(segment.method == 1 for component in context.mapping.components
                      for segment in component.segments[:component.pivot_count - 1])
    if needs_guide and "guide" not in specs:
        raise ValueError("decoded MMR requires verified prepared guide")
    size = width * height * 3
    reader = frame.Reader(paths["p010"].parent, paths["p010"].name, size, 1, pins["p010"])
    try:
        pixels = bytearray()
        for start in range(0, size, 65536):
            pixels.extend(reader.read(min(65536, size - start)))
        reader.finish()
    finally: reader.close()
    allocation = (C.c_uint8 * size).from_buffer(pixels)
    surface = Surface(1, 1, width, height, 1, allocation, size, 0,
                      width * height * 2, width * 2, width * 2)
    surface.frame_id[:] = descriptor.frame_id
    surface.provenance_id[:] = descriptor.provenance_id
    token = (C.c_uint8 * 32)(*descriptor.frame_id)
    provenance = (C.c_uint8 * 32)(*descriptor.provenance_id)
    extract = lib.yb_scaled_surface_extract
    extract.argtypes = [C.POINTER(Surface), C.POINTER(C.c_uint8), C.POINTER(C.c_uint8),
        C.c_uint32, C.c_uint64, C.c_uint32, C.c_uint32, C.POINTER(C.c_uint16)]
    extract.restype = C.c_int
    def chunk(component, start, count, mode):
        output = (C.c_uint16 * count)()
        status = extract(C.byref(surface), token, provenance, component, start, count, mode, output)
        return status, output
    fractional_chunks = 0; checked = 0
    # Preflight ALL three planes before any arithmetic dispatch.
    for component, total in enumerate(counts):
        for start in range(0, total, 65536):
            count = min(65536, total - start)
            status, words = chunk(component, start, count, 1)
            if status: raise ValueError("raw extraction rejected")
            independent = bytearray(count * 2)
            for i in range(count):
                index = start + i
                offset = index * 2 if component == 0 else width * height * 2 + index * 4 + (component - 1) * 2
                independent[i * 2:i * 2 + 2] = pixels[offset:offset + 2]
            if bytes(words) != independent: raise ValueError("raw word preservation differs")
            status, _ = chunk(component, start, count, 2)
            if status not in (0, 4): raise ValueError("exact preflight rejected")
            fractional_chunks += status == 4
            checked += count
    stages = {}; completion = None; dispatches = 0
    adapter = object.__new__(frame.Adapter)
    adapter.lib = lib; adapter.context = context; adapter.descriptor = descriptor; adapter.enabled = True
    u16, i32 = C.POINTER(C.c_uint16), C.POINTER(C.c_int32)
    lib.yb_integration_integer.argtypes = [C.POINTER(frame.Context), C.POINTER(C.c_uint8),
        C.c_int32, C.c_uint64, u16, u16, u16, u16, C.c_uint32, u16, i32, i32, u16]
    lib.yb_integration_integer.restype = C.c_int
    lib.yb_integration_finish.argtypes = [C.POINTER(frame.Context), C.POINTER(frame.Completion)]
    lib.yb_integration_finish.restype = C.c_int
    lib.yb_integration_reset.argtypes = [C.POINTER(frame.Context)]; lib.yb_integration_reset.restype = None
    try:
        if not fractional_chunks:
            for component, channel in enumerate(frame.CHANNELS):
                roles = ["bl_Y", None, None] if component == 0 else ["guide" if "guide" in specs else None, "bl_Cb", "bl_Cr"]
                digests = [hashlib.sha256() for _ in frame.STAGES]
                with ExitStack() as stack:
                    inputs = []
                    for role in roles:
                        value = frame.Reader(*specs[role]) if role else None
                        if value: stack.callback(value.close)
                        inputs.append(value)
                    for start in range(0, counts[component], 65536):
                        count = min(65536, counts[component] - start)
                        status, el = chunk(component, start, count, 2)
                        if status: raise ValueError("exact surface changed after preflight")
                        actual = adapter.process(component, start,
                            [value.read(count) if value else None for value in inputs] + [bytes(el)], count)
                        for digest, generated in zip(digests, actual): digest.update(generated)
                        dispatches += 1
                    for value in inputs:
                        if value: value.finish()
                for (stage, _), digest in zip(frame.STAGES, digests):
                    stages[stage + "_" + channel] = digest.hexdigest()
            completion = adapter.finish(counts)
        unchanged()
        if source_pins() != sources or native.digest(runner_path) != runner_sha256 or any(native.digest(path) != pins[name] for name, path in paths.items()):
            raise ValueError("identity changed during execution")
        if any(native.digest(path) != runtime_pins[str(path)] for path in runtime_paths):
            raise ValueError("runtime changed during execution")
        after = frame.memory_snapshot()
        if not frame.memory_valid(before, after): raise ValueError("memory guard failed")
        return dict(schema="yblod.scaled-surface-private.v1", status="complete",
            route="fractional-policy-required" if fractional_chunks else "exact-whole-code",
            raw_samples_exact=checked, fractional_chunks=fractional_chunks,
            arithmetic_dispatches=dispatches, completion=completion, private_stage_sha256=stages,
            source_sha256=sources, private_input_sha256=pins, prepared_input_sha256=input_pins,
            runner_sha256=runner_sha256,
            private_runtime_sha256=runtime_pins,
            memory_before=before, memory_after=after, old_linear_baseline_compared=False,
            independent_arithmetic_reference=False,
            hardware_source_association_verified_by_this_runner=False)
    finally: adapter.reset()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-sha256", required=True)
    for name in ("library", "instructions", "producer_report", "producer_binary", "p010"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
        parser.add_argument("--" + name.replace("_", "-") + "-sha256", required=True)
    for name in ("prepared_manifest", "baseline", "extraction", "destination"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    args = parser.parse_args()
    result = run(args)
    destination = Path(args.destination); destination.mkdir(mode=0o700)
    frame.save(destination / "private-scaled-surface.json", result)
    print("Raw scaled words verified; route: " + result["route"])


if __name__ == "__main__": main()
