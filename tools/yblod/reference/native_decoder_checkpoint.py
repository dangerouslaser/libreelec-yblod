"""Allowlisted publication of an already completed private decoder comparison.

This does not execute a decoder, establish build provenance or write a result.
Callers provide verified executed-build inventories separately from runtime pins.
No media, instructions, pixel hashes or filesystem paths are published.
"""
import json
import re

SCHEMA = "yblod.native-decoder-frame-summary.v1"
CHANNELS = ("Y", "Cb", "Cr")
STAGES = tuple(s+"_"+c for c in CHANNELS for s in ("mapped", "residual", "sum", "reconstructed"))
RUNTIME_SOURCES = frozenset(("native_decoder_frame.py", "native_decoder_frame_bridge.c",
    "native_decoder_frame_bridge.h", "native_dovi_adapter.h", "native_integration_frame.py",
    "native_integration_probe.c", "native_integration_probe.h", "native_composer.c",
    "native_composer.h", "native_sampling_probe.c", "native_sampling_probe.h", "native_stage.py",
    "base_mapping_stage.py", "nlq_stage.py", "colour_metadata.py", "colour_stage.py",
    "import_rpu.py", "extract_frame.py", "reference.py"))
PRODUCER_SOURCES = frozenset(("native_decoder_ingestion.c", "native_dovi_adapter.c",
    "native_dovi_adapter.h", "native_composer.c", "native_composer.h"))
BRIDGE_SOURCES = frozenset(("native_decoder_frame_bridge.c", "native_decoder_frame_bridge.h",
    "native_dovi_adapter.h", "native_integration_probe.c", "native_integration_probe.h",
    "native_composer.c", "native_composer.h", "native_sampling_probe.c", "native_sampling_probe.h"))
ARTIFACTS = frozenset(("producer_binary", "bridge_library", "ffmpeg_dovi_header", "libavcodec", "libavformat", "libavutil"))
SCOPE = "Decoder-owned instructions to full prepared whole-code reconstruction; no scaling, fractional policy, colour, playback or licensed conformance claim."


def digest(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("invalid public artifact digest")
    return value


def inventory(value, allowed):
    if type(value) is not dict or set(value) != allowed:
        raise ValueError("unexpected public source inventory")
    return {name: digest(value[name]) for name in sorted(allowed)}


def memory(value):
    if type(value) is not dict:
        raise ValueError("missing resource snapshot")
    output = {}
    for role in ("memory.max", "memory.swap.max", "memory.swap.current", "memory.peak"):
        item = value.get(role)
        if type(item) is not str or re.fullmatch("[0-9]+", item) is None:
            raise ValueError("invalid resource scalar")
        output[role] = int(item)
    if not 0 < output["memory.max"] <= 512*1024**2 or output["memory.swap.max"] or output["memory.swap.current"]:
        raise ValueError("unbounded or swapped diagnostic")
    if output["memory.peak"] > output["memory.max"]:
        raise ValueError("resource snapshot exceeded cap")
    events = value.get("memory.events")
    if type(events) is not str:
        raise ValueError("missing resource events")
    rows = [line.split() for line in events.splitlines()]
    if any(len(row) != 2 or re.fullmatch("[0-9]+", row[1]) is None for row in rows):
        raise ValueError("invalid resource events")
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError("duplicate resource event")
    parsed = {key: int(n) for key, n in rows}
    if any(parsed.get(key) != 0 for key in ("max", "oom", "oom_kill")):
        raise ValueError("memory pressure or OOM observed")
    output["events"] = {key: parsed[key] for key in ("max", "oom", "oom_kill")}
    return output


def producer_record(private, artifacts):
    record = private.get("producer")
    if (type(record) is not dict or record.get("schema") != "yblod.native-decoder-ingestion.v1"
            or record.get("status") != "complete" or record.get("original_pts_verified") is not False):
        raise ValueError("completed decoder producer required")
    for key in ("decoder_metadata", "raw_rpu_exact", "el_active_planes_exact", "crc_requested"):
        if record.get(key) is not True: raise ValueError("decoder evidence gate failed")
    for key, value in (("warning_or_error_logs", 0), ("adapter_abi", 1), ("instructions_bytes", 9216), ("local_presentation_index", 64)):
        if type(record.get(key)) is not int or record[key] != value: raise ValueError("decoder producer identity differs")
    for key, lower in (("frames_received", 65), ("packets_sent", 1)):
        if type(record.get(key)) is not int or not lower <= record[key] <= 96: raise ValueError("decoder traversal outside bound")
    if digest(record.get("instructions_sha256")) != digest(private.get("instructions_sha256")):
        raise ValueError("decoder instructions association differs")
    if digest(private.get("producer_binary_sha256")) != artifacts["producer_binary"]:
        raise ValueError("executed producer binary differs")
    versions = {}
    for key in ("avcodec_version", "avformat_version", "avutil_version"):
        n = record.get(key)
        if type(n) is not int or not 0 < n < 2**24: raise ValueError("invalid decoder runtime version")
        versions[key] = n
    return {key: record[key] for key in ("local_presentation_index", "frames_received", "packets_sent",
        "original_pts_verified", "decoder_metadata", "raw_rpu_exact", "el_active_planes_exact",
        "crc_requested", "warning_or_error_logs", "adapter_abi", "instructions_bytes")}, versions


def repair_record(proof):
    if type(proof) is not dict: raise ValueError("independent fixture proof required")
    for key in ("independently_verified", "prefix_byte_exact", "exact_eof_zero_proven"):
        if proof.get(key) is not True: raise ValueError("fixture proof incomplete")
    if type(proof.get("removed_exact_eof_zero_bytes")) is not int or proof["removed_exact_eof_zero_bytes"] != 1:
        raise ValueError("unexpected fixture modification")
    original, derived = digest(proof.get("original_sha256")), digest(proof.get("derived_sha256"))
    if original == derived: raise ValueError("fixture identities do not differ")
    if (type(proof.get("original_bytes")) is not int or type(proof.get("derived_bytes")) is not int
            or not 0 < proof["derived_bytes"] < 4*1024**2 or proof["original_bytes"] != proof["derived_bytes"]+1):
        raise ValueError("fixture size proof differs")
    return dict(independently_verified=True, prefix_byte_exact=True,
                exact_eof_zero_proven=True, removed_exact_eof_zero_bytes=1)


def summarize(private, *, producer_sources, bridge_sources, artifacts, target, compiler_version, fixture_repair_proof):
    """Return only verified completion facts and explicitly named public pins.

    Unknown private fields are never copied. Exact build inventories must come
    from the executed builds, not inferred from this helper's current sources.
    """
    if type(private) is not dict or private.get("status") != "complete":
        raise ValueError("completed native comparison required")
    if private.get("memory_cap_required") is not True or private.get("baseline_kind") != "native-c-integer":
        raise ValueError("capped native baseline required")
    completion = private.get("completion")
    if type(completion) is not dict or set(completion) != {"kind", "counts", "diagnostic_queries"}:
        raise ValueError("invalid completion")
    counts = completion["counts"]
    if (type(counts) is not list or len(counts) != 3 or any(type(n) is not int or not 0 < n <= 8192**2 for n in counts)
            or counts[0] != 4*counts[1] or counts[1] != counts[2]
            or completion["kind"] != "arithmetic-frame-complete"
            or type(completion["diagnostic_queries"]) is not int or completion["diagnostic_queries"] != 0):
        raise ValueError("incomplete whole-code frame")
    stages = private.get("stages")
    inputs = private.get("input_sha256")
    if type(stages) is not dict or set(stages) != set(STAGES) or type(inputs) is not dict:
        raise ValueError("all twelve stages required")
    published_stages = {}
    for role in STAGES:
        item = stages[role]
        expected = counts[CHANNELS.index(role.rsplit("_", 1)[1])]
        if (type(item) is not dict or type(item.get("samples")) is not int
                or item["samples"] != expected or item.get("byte_exact") is not True
                or digest(item.get("sha256")) != digest(inputs.get(role))):
            raise ValueError("stage comparison incomplete")
        published_stages[role] = dict(samples=expected, byte_exact=True)
    before, after = memory(private.get("memory_before")), memory(private.get("memory_after"))
    if before["memory.max"] != after["memory.max"] or after["memory.peak"] < before["memory.peak"]:
        raise ValueError("resource scope changed")
    producer_before = memory(private.get("producer_memory_before"))
    producer_after = memory(private.get("producer_memory_after"))
    if (producer_before["memory.max"] != producer_after["memory.max"]
            or producer_after["memory.peak"] < producer_before["memory.peak"]):
        raise ValueError("producer resource scope changed")
    public_artifacts = inventory(artifacts, ARTIFACTS)
    producer, runtime_versions = producer_record(private, public_artifacts)
    fixture_repair = repair_record(fixture_repair_proof)
    if digest(private.get("library_sha256")) != public_artifacts["bridge_library"]:
        raise ValueError("executed bridge library differs")
    if target not in ("ollie-cpu", "libreelec-vm-cpu") or type(target) is not str:
        raise ValueError("unsupported execution target")
    if type(compiler_version) is not str or re.fullmatch("GCC [0-9]+(?:\\.[0-9]+){1,2}", compiler_version) is None:
        raise ValueError("invalid compiler version")
    return dict(schema=SCHEMA, status="complete",
        execution_targets=dict(producer="libreelec-vm-cpu", reconstruction=target), compiler_version=compiler_version,
        scope=SCOPE, producer=producer, runtime_versions=runtime_versions, fixture_repair=fixture_repair,
        runtime_source_sha256=inventory(private.get("source_sha256"), RUNTIME_SOURCES),
        executed_producer_source_sha256=inventory(producer_sources, PRODUCER_SOURCES),
        executed_bridge_source_sha256=inventory(bridge_sources, BRIDGE_SOURCES),
        public_artifact_sha256=public_artifacts, stages=published_stages,
        completion=dict(kind=completion["kind"], counts=counts[:], diagnostic_queries=0),
        resources=dict(before=before, after=after, peak_scope="Snapshots before comparison completion, not final scope lifetime"),
        producer_resources=dict(before=producer_before, after=producer_after,
            peak_scope="Snapshots before producer scope exit, not final scope lifetime"),
        baseline_kind="native-c-integer", memory_guard_passed=True,
        gpu_attempted=False, playback_attempted=False)


def validate_public(report):
    """Strict replay validation, not fresh execution or private-hash verification.

    The omitted private identities cannot be re-established from this report.
    Reconstruct only a validation witness to reuse the same public invariants.
    """
    keys = {"schema","status","execution_targets","compiler_version","scope","producer","runtime_versions",
        "fixture_repair","runtime_source_sha256","executed_producer_source_sha256",
        "executed_bridge_source_sha256","public_artifact_sha256","stages","completion","resources",
        "baseline_kind","memory_guard_passed","gpu_attempted","playback_attempted","producer_resources"}
    if type(report) is not dict or set(report) != keys:
        raise ValueError("unexpected public checkpoint fields")
    if (type(report.get("stages")) is not dict or set(report["stages"]) != set(STAGES)
            or type(report.get("producer")) is not dict or type(report.get("runtime_versions")) is not dict
            or type(report.get("resources")) is not dict or set(report["resources"]) != {"before","after","peak_scope"}):
        raise ValueError("invalid public checkpoint structure")
    if (type(report["execution_targets"]) is not dict or set(report["execution_targets"]) != {"producer","reconstruction"}
            or report["execution_targets"]["producer"] != "libreelec-vm-cpu"
            or type(report["producer_resources"]) is not dict or set(report["producer_resources"]) != {"before","after","peak_scope"}):
        raise ValueError("invalid separate execution contexts")
    producer_keys = {"local_presentation_index","frames_received","packets_sent","original_pts_verified",
        "decoder_metadata","raw_rpu_exact","el_active_planes_exact","crc_requested","warning_or_error_logs",
        "adapter_abi","instructions_bytes"}
    if set(report["producer"]) != producer_keys or set(report["runtime_versions"]) != {"avcodec_version","avformat_version","avutil_version"}:
        raise ValueError("unexpected producer fields")
    inventory(report["public_artifact_sha256"], ARTIFACTS)
    if (type(report["fixture_repair"]) is not dict or set(report["fixture_repair"]) !=
            {"independently_verified","prefix_byte_exact","exact_eof_zero_proven","removed_exact_eof_zero_bytes"}):
        raise ValueError("unexpected fixture proof fields")
    def snapshot(value):
        if type(value) is not dict or set(value) != {"memory.max","memory.swap.max","memory.swap.current","memory.peak","events"}:
            raise ValueError("unexpected resource fields")
        if any(type(value[key]) is not int or value[key] < 0 for key in ("memory.max","memory.swap.max","memory.swap.current","memory.peak")):
            raise ValueError("invalid resource types")
        events = value["events"]
        if type(events) is not dict or set(events) != {"max","oom","oom_kill"} or any(type(n) is not int or n != 0 for n in events.values()):
            raise ValueError("invalid public events")
        result = {key:str(value[key]) for key in ("memory.max","memory.swap.max","memory.swap.current","memory.peak")}
        result["memory.events"] = "\n".join(key+" "+str(n) for key,n in events.items())
        return result
    opaque = "0"*64
    stages = {}
    for role,item in report["stages"].items():
        if type(item) is not dict or set(item) != {"samples","byte_exact"}: raise ValueError("unexpected stage fields")
        stages[role] = dict(item, sha256=opaque)
    producer = dict(report["producer"], **report["runtime_versions"])
    producer.update(schema="yblod.native-decoder-ingestion.v1", status="complete", instructions_sha256=opaque)
    private = dict(status=report["status"], memory_cap_required=True, baseline_kind=report["baseline_kind"],
        completion=report["completion"], stages=stages, input_sha256={role:opaque for role in STAGES},
        producer=producer, instructions_sha256=opaque,
        producer_binary_sha256=report["public_artifact_sha256"].get("producer_binary"),
        library_sha256=report["public_artifact_sha256"].get("bridge_library"),
        source_sha256=report["runtime_source_sha256"], memory_before=snapshot(report["resources"]["before"]),
        memory_after=snapshot(report["resources"]["after"]),
        producer_memory_before=snapshot(report["producer_resources"]["before"]),
        producer_memory_after=snapshot(report["producer_resources"]["after"]))
    if type(report["fixture_repair"]) is not dict: raise ValueError("invalid fixture repair")
    repair = dict(report["fixture_repair"], original_sha256="1"*64, derived_sha256="2"*64,
                  original_bytes=2, derived_bytes=1)
    rebuilt = summarize(private, producer_sources=report["executed_producer_source_sha256"],
        bridge_sources=report["executed_bridge_source_sha256"], artifacts=report["public_artifact_sha256"],
        target=report["execution_targets"]["reconstruction"], compiler_version=report["compiler_version"], fixture_repair_proof=repair)
    if json.dumps(report, sort_keys=True, allow_nan=False) != json.dumps(rebuilt, sort_keys=True, allow_nan=False):
        raise ValueError("public checkpoint invariant differs")
    return report


def replay_json(raw):
    """Validate bounded JSON bytes supplied by the caller; does not open paths."""
    if type(raw) is not bytes or len(raw) > 1024**2: raise ValueError("bounded checkpoint bytes required")
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError("duplicate checkpoint key")
            result[key] = value
        return result
    def invalid(value): raise ValueError("noninteger JSON number")
    return validate_public(json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=invalid))
