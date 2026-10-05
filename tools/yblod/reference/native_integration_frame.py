#!/usr/bin/env python3
"""Private full-frame C-adapter check; no movie pixels/metadata in public summary.

Prepared whole-code input only. No scaling, fractional policy, colour, GPU,
playback or fresh film/CRC verification. One C dispatch per bounded chunk.
"""
import argparse
from contextlib import ExitStack
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import colour_metadata as association
import native_stage as native
import reference
from base_mapping_stage import BaseMappingConfig
from nlq_stage import NLQConfig

ROOT = Path(__file__).resolve().parent
CHANNELS = ("Y", "Cb", "Cr")
STAGES = (("mapped", 2), ("residual", 4), ("sum", 4), ("reconstructed", 2))
SOURCES = ("native_integration_frame.py", "native_integration_probe.c", "native_integration_probe.h",
           "native_composer.c", "native_composer.h", "native_sampling_probe.c", "native_sampling_probe.h",
           "native_stage.py", "base_mapping_stage.py", "nlq_stage.py", "colour_metadata.py",
           "colour_stage.py", "import_rpu.py", "extract_frame.py", "reference.py")
BUILD_SCHEMA = "yblod.native-integration-build.v1"
SUMMARY_SCHEMA = "yblod.native-integration-frame-summary.v1"


class Descriptor(C.Structure):
    _fields_ = [("version", C.c_uint32), ("input_kind", C.c_uint32),
                ("width", C.c_uint32), ("height", C.c_uint32),
                ("output_depth", C.c_int32), ("enhancement_enabled", C.c_int32),
                ("frame_id", C.c_uint8*32), ("provenance_id", C.c_uint8*32)]


class Sampling(C.Structure):
    _fields_ = [("width", C.c_uint32), ("height", C.c_uint32),
                ("origin_x", C.c_int64), ("origin_y", C.c_int64),
                ("step_x", C.c_int64), ("step_y", C.c_int64),
                ("coordinate_fractional_bits", C.c_uint32), ("method", C.c_uint32),
                ("edge", C.c_uint32), ("native_depth", C.c_uint32),
                ("fractional_bits", C.c_uint32), ("word_normalization_divisor", C.c_uint32)]


class Context(C.Structure):
    _fields_ = [("initialized", C.c_uint32), ("finalized", C.c_uint32),
                ("descriptor", Descriptor), ("mapping", native.Mapping),
                ("nlq", native.NLQ*3), ("sampling", Sampling),
                ("consumed", C.c_uint64*3), ("diagnostic_queries", C.c_uint64)]


class Completion(C.Structure):
    _fields_ = [("kind", C.c_uint32), ("counts", C.c_uint64*3),
                ("diagnostic_queries", C.c_uint64)]


def source_hashes():
    return {name: native.digest(ROOT/name) for name in SOURCES}


def save(path, value):
    """Publish only a fully serialized JSON file, without overwriting anything."""
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()
    pending = path.with_name(path.name+".pending")
    with pending.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("short report write")
    os.link(pending, path)
    try:
        pending.unlink()
    except OSError:
        pass  # Publication is the commit point; housekeeping cannot undo success.


def build(destination, *, compiler="cc"):
    destination = Path(destination).resolve()
    destination.mkdir(mode=0o700)
    pins = source_hashes()
    library = destination/"libnative_integration.so"
    command = [compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
               "-Wconversion", "-Wshadow", *(str(ROOT/name) for name in
               ("native_integration_probe.c", "native_composer.c", "native_sampling_probe.c")),
               "-o", str(library)]
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True, timeout=30).stdout
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError("native build failed: "+result.stderr)
    if source_hashes() != pins:
        raise ValueError("source changed during build")
    save(destination/"build.json", dict(schema=BUILD_SCHEMA, status="complete", abi_version=1,
         library=library.name, library_sha256=native.digest(library), source_sha256=pins,
         command=command, compiler_version=version))
    return library


class Adapter:
    def __init__(self, library, manifest, identity, provenance):
        if sys.byteorder != "little":
            raise ValueError("this byte-buffer diagnostic requires a little-endian host")
        self.path = Path(library).resolve()
        self.raw_record, record = native._record(self.path.parent/"build.json")
        self.pins = source_hashes()
        if (record.get("schema") != BUILD_SCHEMA or record.get("status") != "complete"
                or type(record.get("abi_version")) is not int or record["abi_version"] != 1
                or record.get("library") != self.path.name or record.get("source_sha256") != self.pins
                or record.get("library_sha256") != native.digest(self.path)):
            raise ValueError("native adapter build provenance mismatch")
        self.library_hash = record["library_sha256"]
        self.lib = C.CDLL(str(self.path))
        self.unchanged()
        checks = (("yb_integration_abi_version", 1, C.c_uint32),
                  ("yb_abi_version", 1, C.c_uint32))
        for name, expected, result_type in checks:
            query = getattr(self.lib, name); query.argtypes=[]; query.restype=result_type
            if query() != expected:
                raise ValueError("native adapter ABI version mismatch")
        structures = {"yb_sizeof_mapping_config": native.Mapping, "yb_sizeof_nlq_config": native.NLQ,
                      "yb_sizeof_component_mapping": native.Component, "yb_sizeof_segment": native.Segment,
                      "yb_integration_sizeof_descriptor": Descriptor, "yb_integration_sizeof_context": Context,
                      "yb_integration_sizeof_completion": Completion, "yb_integration_sizeof_sampling_contract": Sampling}
        for name, structure in structures.items():
            query = getattr(self.lib, name); query.argtypes=[]; query.restype=C.c_uint64
            if query() != C.sizeof(structure):
                raise ValueError("native adapter ABI size mismatch")
        u16, i32 = C.POINTER(C.c_uint16), C.POINTER(C.c_int32)
        self.lib.yb_integration_init.argtypes = [C.POINTER(Context), C.POINTER(Descriptor), C.POINTER(native.Mapping), C.POINTER(native.NLQ), C.POINTER(Sampling)]
        self.lib.yb_integration_integer.argtypes = [C.POINTER(Context), C.POINTER(C.c_uint8), C.c_int32, C.c_uint64, u16, u16, u16, u16, C.c_uint32, u16, i32, i32, u16]
        self.lib.yb_integration_finish.argtypes = [C.POINTER(Context), C.POINTER(Completion)]
        self.lib.yb_integration_reset.argtypes = [C.POINTER(Context)]
        for name in ("init", "integer", "finish"):
            getattr(self.lib, "yb_integration_"+name).restype=C.c_int
        self.lib.yb_integration_reset.restype=None
        metadata = manifest["metadata"]
        mapping = BaseMappingConfig.from_mappings(metadata["mappings"], bit_depth=metadata["bl_bit_depth"], denominator=metadata["coefficient_log2_denom"])
        _, encoded = native._mapping(mapping)
        self.enabled = not metadata["disable_residual"]
        nlqs = (native.NLQ*3)(*(native._nlq(NLQConfig.from_mapping(p, bit_depth=metadata["el_bit_depth"], denominator=metadata["coefficient_log2_denom"]))[1]
                                for p in metadata["nlq"])) if self.enabled else None
        self.descriptor = Descriptor(1, 1, manifest["width"], manifest["height"], metadata["output_bit_depth"], int(self.enabled))
        for field, value in (("frame_id", identity), ("provenance_id", provenance)):
            token = hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).digest()
            getattr(self.descriptor, field)[:] = token
        self.context = Context()
        if self.lib.yb_integration_init(C.byref(self.context), C.byref(self.descriptor), C.byref(encoded), nlqs, None):
            raise ValueError("native adapter initialization rejected")

    def unchanged(self):
        if (native.digest(self.path) != self.library_hash or source_hashes() != self.pins
                or native._record(self.path.parent/"build.json")[0] != self.raw_record):
            raise ValueError("native adapter artifacts changed")

    def process(self, component, start, raw_planes, count):
        native._integer(count, "chunk count", 1, 65536)
        native._integer(component, "component", 0, 2)
        native._integer(start, "global start", 0, 8192**2)
        buffers = []
        for index, raw in enumerate(raw_planes):
            if raw is None:
                buffers.append(None if index == 3 else (C.c_uint16*count)())
            elif type(raw) is not bytes or len(raw) != count*2:
                raise ValueError("wrong input chunk bytes")
            else:
                buffers.append((C.c_uint16*count).from_buffer_copy(raw))
        if len(buffers) != 4 or (buffers[3] is not None) != self.enabled:
            raise ValueError("explicit four-plane enabled/disabled contract required")
        outputs = ((C.c_uint16*count)(), (C.c_int32*count)(), (C.c_int32*count)(), (C.c_uint16*count)())
        status = self.lib.yb_integration_integer(C.byref(self.context), self.descriptor.frame_id,
                     component, start, *buffers, count, *outputs)
        if status:
            raise ValueError("native adapter chunk rejected (status%d)" % status)
        return tuple(bytes(output) for output in outputs)

    def finish(self, counts):
        result = Completion()
        if self.lib.yb_integration_finish(C.byref(self.context), C.byref(result)):
            raise ValueError("native adapter finalization rejected")
        if result.kind != 1 or list(result.counts) != list(counts) or result.diagnostic_queries != 0:
            raise ValueError("wrong native completion kind or counts")
        return dict(kind="arithmetic-frame-complete", counts=list(result.counts), diagnostic_queries=0)

    def reset(self):
        self.lib.yb_integration_reset(C.byref(self.context))


class Reader:
    def __init__(self, root, filename, samples, size, expected):
        root = Path(root).resolve()
        if type(filename) is not str or not filename or Path(filename).is_absolute():
            raise ValueError("relative data filename required")
        if (root/filename).is_symlink():
            raise ValueError("data-file symlinks are not accepted")
        self.path = (root/filename).resolve()
        if not self.path.is_relative_to(root):
            raise ValueError("data file escapes bundle")
        self.expected = association._sha(expected)
        self.stream = native._regular(self.path)
        self.initial = os.fstat(self.stream.fileno())
        self.total, self.size, self.used = samples*size, size, 0
        self.digest = hashlib.sha256()
        if self.initial.st_size != self.total:
            self.close(); raise ValueError("wrong data file size")

    def read(self, samples):
        native._integer(samples, "read samples", 1, 65536)
        amount = samples*self.size
        if self.used+amount > self.total:
            raise ValueError("extra data requested")
        raw = self.stream.read(amount)
        if len(raw) != amount:
            raise ValueError("short data read")
        self.used += amount; self.digest.update(raw)
        return raw

    def finish(self):
        if self.used != self.total or self.stream.read(1):
            raise ValueError("incomplete or extra data")
        native._unchanged(self.path, self.initial, os.fstat(self.stream.fileno()))
        if self.digest.hexdigest() != self.expected:
            raise ValueError("data hash mismatch")
        return self.expected

    def close(self):
        self.stream.close()


def scan(spec):
    reader = Reader(*spec)
    try:
        for start in range(0, spec[2], 65536):
            reader.read(min(65536, spec[2]-start))
        return reader.finish()
    finally:
        reader.close()


def prepare(manifest_path, baseline, extraction, *, allow_reference_baseline=False):
    manifest_path, baseline = Path(manifest_path).resolve(), Path(baseline).resolve()
    manifest, manifest_hash = association._json(manifest_path.parent, manifest_path.name)
    report, report_hash = association._json(baseline, "report.json")
    verified = association.load(baseline, extraction)
    reference.validate(manifest)
    if (report_hash != verified["composer_report_sha256"] or report.get("manifest_sha256") != manifest_hash
            or not association._same(report["input_manifest"], manifest)):
        raise ValueError("prepared/baseline/source association differs")
    baseline_kind = "native-c-integer"
    if report.get("backend") != "native":
        if not allow_reference_baseline or report.get("backend") not in (None, "python"):
            raise ValueError("pinned native baseline required")
        baseline_kind = "explicit-test-reference"
    else:
        provenance = report.get("native_provenance", {})
        build_record = provenance.get("build_record", {})
        if (provenance.get("backend") != "native-c-integer" or type(provenance.get("abi_version")) is not int
                or provenance["abi_version"] != 1 or build_record.get("status") != "complete"
                or build_record.get("schema") != native.SCHEMA
                or build_record.get("library_sha256") != provenance.get("library_sha256")
                or build_record.get("source_sha256") != provenance.get("source_sha256")):
            raise ValueError("invalid saved native baseline provenance")
        association._sha(provenance["library_sha256"]); association._sha(provenance["build_record_sha256"])
        if set(provenance["source_sha256"]) != {"native_composer.c", "native_composer.h", "native_stage.py", "base_mapping_stage.py", "nlq_stage.py"}:
            raise ValueError("saved native baseline lacks exact source pins")
        if (type(build_record.get("abi_version")) is not int or build_record["abi_version"] != 1
                or hashlib.sha256((json.dumps(build_record, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()).hexdigest() != provenance["build_record_sha256"]):
            raise ValueError("saved native build record identity mismatch")
        for value in provenance["source_sha256"].values(): association._sha(value)
    count = manifest["width"]*manifest["height"]
    counts = (count, count//4, count//4)
    metadata = manifest["metadata"]
    enabled = not metadata["disable_residual"]
    guide = any(s["method"] == "mmr" for curve in metadata["mappings"] for s in curve["segments"])
    if guide and not manifest.get("mmr_luma"):
        raise ValueError("explicit prepared guide required")
    specs, filenames = {}, set()
    for layer in (("bl", "el") if enabled else ("bl",)):
        if set(manifest[layer]["planes"]) != set(CHANNELS):
            raise ValueError("three declared component planes required")
        for component, channel in enumerate(CHANNELS):
            filename = manifest[layer]["planes"][channel]
            specs[layer+"_"+channel] = (manifest_path.parent, filename, counts[component], 2, report["input_sha256"][filename])
            filenames.add(filename)
    if guide:
        filename = manifest["mmr_luma"]
        specs["guide"] = (manifest_path.parent, filename, counts[1], 2, report["input_sha256"][filename]); filenames.add(filename)
    if set(report["input_sha256"]) != filenames:
        raise ValueError("baseline consumed input set differs")
    expected_stages = {name+"_"+channel for channel in CHANNELS for name, _ in STAGES}
    if set(report["stages"]) != expected_stages:
        raise ValueError("exactly twelve baseline stages required")
    for component, channel in enumerate(CHANNELS):
        for stage, size in STAGES:
            role = stage+"_"+channel; record = report["stages"][role]
            if type(record["samples"]) is not int or record["samples"] != counts[component]:
                raise ValueError("baseline stage count mismatch")
            specs[role] = (baseline, record["file"], counts[component], size, record["sha256"])
    pins = {role: scan(spec) for role, spec in specs.items()}
    pins.update(manifest=manifest_hash, baseline_report=report_hash,
                extraction=verified["provenance"]["source_extraction_sha256"],
                rpu_json=verified["provenance"]["rpu_json_sha256"], rpu_binary=verified["provenance"]["rpu_binary_sha256"])
    def unchanged():
        for spec in specs.values(): scan(spec)
        if (association._json(manifest_path.parent, manifest_path.name)[1] != manifest_hash
                or not association._same(association.load(baseline, extraction), verified)):
            raise ValueError("source association changed")
    return manifest, verified, specs, pins, counts, baseline_kind, unchanged


def memory_snapshot():
    try:
        entry = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
        root = Path("/sys/fs/cgroup")/entry.lstrip("/")
        return {name: (root/name).read_text().strip() for name in
                ("memory.max", "memory.swap.max", "memory.swap.current", "memory.peak", "memory.events")}
    except (OSError, StopIteration):
        return {}


def memory_valid(before, after=None):
    if (before.get("memory.swap.max") != "0" or before.get("memory.swap.current") != "0"
            or not before.get("memory.max", "").isdigit() or not 0 < int(before["memory.max"]) <= 512*1024**2):
        return False
    if after is None: return True
    if (after.get("memory.max") != before["memory.max"] or after.get("memory.swap.max") != "0"
            or after.get("memory.swap.current") != "0"):
        return False
    a, b = (dict(line.split() for line in item.get("memory.events", "").splitlines()) for item in (before, after))
    return all(a.get(key, "").isdigit() and b.get(key, "").isdigit() and a[key] == b[key]
               for key in ("max", "oom", "oom_kill"))


def public_summary(private):
    status = private["status"]
    if status not in ("complete", "failed"): raise ValueError("invalid status")
    result = dict(schema=SUMMARY_SCHEMA, status=status,
        scope="Full prepared whole-code C adapter check; no resampling, fractional policy, colour, GPU, playback or licensed conformance claim.",
        source_association="Saved extracted-RPU association; no fresh CRC parse or film rehash.")
    allowed_inputs = {"manifest", "baseline_report", "extraction", "rpu_json", "rpu_binary", "guide"}
    allowed_inputs |= {layer+"_"+c for layer in ("bl", "el") for c in CHANNELS}
    stage_names = {s+"_"+c for s, _ in STAGES for c in CHANNELS}
    allowed_inputs |= stage_names
    for field, allowed in (("source_sha256", set(SOURCES)), ("input_sha256", allowed_inputs)):
        if not set(private[field]) <= allowed: raise ValueError("unexpected public hash role")
        result[field] = {key: association._sha(value) for key, value in private[field].items()}
    for field in ("library_sha256", "build_record_sha256"):
        result[field] = association._sha(private[field])
    for field in ("association_verified", "all_data_rechecked", "memory_guard_passed", "memory_cap_required", "enhancement_enabled", "guide_consumed"):
        if type(private[field]) is not bool: raise ValueError("strict summary boolean required")
        result[field] = private[field]
    if not result["memory_cap_required"] and result["memory_guard_passed"]:
        raise ValueError("bypassed memory guard must not claim passed")
    result["memory_guard_state"] = ("bypassed-host-test" if not result["memory_cap_required"] else
                                    "enforced-passed" if result["memory_guard_passed"] else "enforced-failed")
    if private["baseline_kind"] not in ("native-c-integer", "explicit-test-reference"):
        raise ValueError("invalid baseline role")
    result["baseline_kind"] = private["baseline_kind"]
    counts = private["expected_counts"]
    if (type(counts) is not list or len(counts) != 3 or any(type(n) is not int or not 1 <= n <= 8192**2 for n in counts)
            or counts[0] != 4*counts[1] or counts[1] != counts[2]): raise ValueError("invalid component counts")
    result["expected_counts"] = counts[:]
    expected_inputs = {"manifest", "baseline_report", "extraction", "rpu_json", "rpu_binary"} | stage_names
    expected_inputs |= {"bl_"+c for c in CHANNELS}
    if result["enhancement_enabled"]: expected_inputs |= {"el_"+c for c in CHANNELS}
    if result["guide_consumed"]: expected_inputs.add("guide")
    if set(result["input_sha256"]) != expected_inputs or set(result["source_sha256"]) != set(SOURCES):
        raise ValueError("incomplete source or consumed-input hash evidence")
    result["stages"] = {}
    for role, item in private["stages"].items():
        if role not in stage_names: raise ValueError("invalid stage role")
        expected = counts[CHANNELS.index(role.rsplit("_", 1)[1])]
        if type(item["samples"]) is not int or item["samples"] != expected or item["byte_exact"] is not True:
            raise ValueError("invalid stage comparison")
        actual, baseline = association._sha(item["sha256"]), association._sha(item["baseline_sha256"])
        if actual != baseline or baseline != result["input_sha256"][role]: raise ValueError("stage digest mismatch")
        result["stages"][role] = dict(samples=expected, sha256=actual, baseline_sha256=baseline, byte_exact=True)
    completion = private.get("completion")
    result["completion"] = None
    if completion is not None:
        expected = dict(kind="arithmetic-frame-complete", counts=counts, diagnostic_queries=0)
        if not association._same(completion, expected): raise ValueError("invalid completion")
        result["completion"] = expected
    resources = private.get("resources", {})
    result["resources"] = {key: value for key, value in resources.items() if key in
        ("charged_peak_bytes", "swap_bytes", "oom_events", "oom_kill_events", "limit_events") and type(value) is int and value >= 0}
    if status == "complete" and (set(result["stages"]) != stage_names or result["completion"] is None
            or not all(result[key] for key in ("association_verified", "all_data_rechecked"))
            or (result["memory_cap_required"] and not result["memory_guard_passed"])):
        raise ValueError("incomplete evidence cannot publish success")
    return result


def run(library, prepared_manifest, baseline, extraction, destination, *, chunk_samples=65536,
        require_memory_cap=True, allow_reference_baseline=False):
    native._integer(chunk_samples, "chunk_samples", 1, 65536)
    if type(require_memory_cap) is not bool or type(allow_reference_baseline) is not bool:
        raise ValueError("explicit boolean diagnostic controls required")
    before = memory_snapshot()
    if require_memory_cap and not memory_valid(before): raise ValueError("requires <=512MiB and zero job swap")
    manifest, verified, specs, pins, counts, kind, unchanged = prepare(prepared_manifest, baseline, extraction,
                                                allow_reference_baseline=allow_reference_baseline)
    adapter = Adapter(library, manifest, verified["identity"], pins)
    output = Path(destination).resolve(); output.mkdir(mode=0o700)
    private = dict(status="failed", source_sha256=adapter.pins, input_sha256=pins,
        library_sha256=adapter.library_hash, build_record_sha256=hashlib.sha256(adapter.raw_record).hexdigest(),
        association_verified=True, all_data_rechecked=False, memory_guard_passed=False,
        memory_cap_required=require_memory_cap, baseline_kind=kind, expected_counts=list(counts),
        enhancement_enabled=adapter.enabled, guide_consumed="guide" in specs,
        stages={}, cgroup_before=before)
    try:
        for component, channel in enumerate(CHANNELS):
            roles = (["bl_Y", None, None] if component == 0 else
                     ["guide" if "guide" in specs else None, "bl_Cb", "bl_Cr"])
            roles.append("el_"+channel if adapter.enabled else None)
            with ExitStack() as stack:
                def reader(role):
                    if role is None: return None
                    value = Reader(*specs[role]); stack.callback(value.close); return value
                inputs = [reader(role) for role in roles]
                baseline_readers = [reader(stage+"_"+channel) for stage, _ in STAGES]
                digests = [hashlib.sha256() for _ in STAGES]
                for start in range(0, counts[component], chunk_samples):
                    count = min(chunk_samples, counts[component]-start)
                    raw = [value.read(count) if value else None for value in inputs]
                    actual = adapter.process(component, start, raw, count)
                    for index, (generated, saved) in enumerate(zip(actual, baseline_readers)):
                        if generated != saved.read(count): raise ValueError("full-stage byte mismatch")
                        digests[index].update(generated)
                for value in inputs:
                    if value: value.finish()
                for (stage, _), saved, digest in zip(STAGES, baseline_readers, digests):
                    role = stage+"_"+channel
                    expected_hash = saved.finish()
                    if digest.hexdigest() != expected_hash: raise ValueError("generated stage digest differs")
                    private["stages"][role] = dict(samples=counts[component], sha256=digest.hexdigest(), baseline_sha256=expected_hash, byte_exact=True)
        private["completion"] = adapter.finish(counts)
        unchanged(); adapter.unchanged()
        private["all_data_rechecked"] = True
        private["status"] = "complete"
    except Exception as error:
        private["error"] = dict(type=type(error).__name__, message=str(error))
    finally:
        adapter.reset()
    after = memory_snapshot(); private["cgroup_after"] = after
    private["memory_guard_passed"] = require_memory_cap and memory_valid(before, after)
    if require_memory_cap and not private["memory_guard_passed"]: private["status"] = "failed"
    events = dict(line.split() for line in after.get("memory.events", "").splitlines())
    private["resources"] = {name: int(value) for name, value in (
        ("charged_peak_bytes", after.get("memory.peak", "")), ("swap_bytes", after.get("memory.swap.current", "")),
        ("oom_events", events.get("oom", "")), ("oom_kill_events", events.get("oom_kill", "")), ("limit_events", events.get("max", ""))) if value.isdigit()}
    summary = public_summary(private)
    save(output/"private-report.json", private)
    save(output/"public-summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("build"); compile_parser.add_argument("destination")
    execute = commands.add_parser("run")
    for name in ("library", "prepared_manifest", "baseline", "extraction", "destination"): execute.add_argument(name)
    execute.add_argument("--chunk-samples", type=int, default=65536)
    arguments = vars(parser.parse_args()); command = arguments.pop("command")
    if command == "build": build(**arguments)
    else:
        result = run(**arguments)
        print(json.dumps({"status": result["status"], "stages": len(result["stages"])}))
        raise SystemExit(result["status"] != "complete")
