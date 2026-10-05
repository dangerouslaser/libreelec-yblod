"""Strict public replay of a reviewed handoff, never a private-media exporter."""
import copy
import json
import re

SCHEMA = "yblod.native-scaled-surface-checkpoint.v1"
SOURCES = (
    "native_scaled_surface.c", "native_scaled_surface.h",
    "native_decoder_frame_bridge.c", "native_decoder_frame_bridge.h",
    "native_integration_probe.c", "native_integration_probe.h",
    "native_sampling_probe.c", "native_sampling_probe.h",
    "native_composer.c", "native_composer.h", "native_dovi_adapter.h")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def _pins(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError("incorrect public pin inventory")
    if any(type(v) is not str or not HASH.fullmatch(v) for v in value.values()):
        raise ValueError("invalid public pin")
    return dict(value)


def _exact(value, expected):
    if type(value) is not type(expected):
        raise ValueError("incorrect field type")
    if type(expected) is dict:
        if set(value) != set(expected):
            raise ValueError("incorrect field inventory")
        for k, v in expected.items():
            _exact(value[k], v)
    elif type(expected) is list:
        if len(value) != len(expected):
            raise ValueError("incorrect list size")
        for a, b in zip(value, expected):
            _exact(a, b)
    elif value != expected:
        raise ValueError("incorrect checkpoint claim")


FIXED = dict(
    schema=SCHEMA, status="complete",
    execution_targets=dict(scaler="libreelec-vm-intel", consumer="ollie-cpu"),
    geometry=dict(input=[1920,1080], output=[3840,2160]),
    submitted_request=dict(input_fourcc="P010",output_fourcc="P010",
        surface_contract="advertised",output_surface_advertised=True,
        filter_flags=0,pipeline_flags=0,colour_standard=12,colour_range=2,
        input_chroma_siting=6,output_chroma_siting=6),
    association=dict(saved_el_planes_match_extraction_and_decoder=True,
        original_packed_words_checked=3110400, original_packed_words_exact=True,
        externally_verified=True, verified_by_consumer_runner=False),
    hardware=dict(copy_byte_exact=True, native_vpp_byte_exact=True,
        enlargement_repeats=2, enlargement_repeat_byte_exact=True,
        output_words=12441600, fractional_words=0,
        own_vpp_engine_delta_ns=[dict(render=0,copy=0,video=0,video_enhance=9263956),
            dict(render=0,copy=0,video=0,video_enhance=6725784)],
        subblock_verified=False, driver_binary_prepost_verified=False,
        driver_identity_sampling="after-only"),
    consumer=dict(raw_words_byte_exact=12441600, arithmetic_dispatches=191,
        complete_component_counts=[8294400,2073600,2073600], diagnostic_queries=0,
        route="exact-whole-code", old_linear_baseline_compared=False,
        independent_arithmetic_reference=False),
    resources=dict(memory_max_bytes=536870912, memory_swap_max_bytes=0,
        peak_snapshot_bytes=245694464, observed_swap_bytes=0,
        scaler_peak_snapshot_bytes=[107167744,106897408],
        observed_limit_events=0, observed_oom_events=0, observed_oom_kill_events=0,
        snapshot_scope="before-wrapper-exit-not-final-lifetime-or-total-gpu-memory"),
    limitations=dict(playback_benchmark=False, licensed_conformance=False,
        sk4_accuracy_improvement=False, fractional_quantizer_selected=False,
        production_y416_acceptance=False, amd_measured=False))


def replay(value):
    if type(value) is not dict or set(value) != set(FIXED) | {"pins"}:
        raise ValueError("incorrect report inventory")
    _exact({k:value[k] for k in FIXED}, FIXED)
    pins = value["pins"]
    if type(pins) is not dict or set(pins) != {"engine_sources", "consumer_source", "sdk_library",
            "scaler_artifacts", "system_libraries", "consumer_runtime", "driver_after_only"}:
        raise ValueError("incorrect pin groups")
    _pins(pins["engine_sources"], SOURCES)
    _pins(pins["consumer_source"], ["native_scaled_surface_frame.py"])
    _pins(pins["sdk_library"], ["native_scaled_surface_chain.so"])
    _pins(pins["scaler_artifacts"], ["packer_source", "packer_binary", "probe_source",
          "probe_accounting_header", "probe_binary", "wrapper_source"])
    _pins(pins["system_libraries"], ["libva", "libva_drm", "libdrm"])
    _pins(pins["consumer_runtime"], ["python3.12", "ld-linux-x86-64.so.2", "libc.so.6"])
    _pins(pins["driver_after_only"], ["intel_ihd_driver"])
    return value


def replay_json(raw):
    if type(raw) is not bytes or len(raw)>1024**2:
        raise ValueError("bounded bytes required")
    def pairs(items):
        value = {}
        for k,v in items:
            if k in value:
                raise ValueError("duplicate key")
            value[k]=v
        return value
    def forbidden(_):
        raise ValueError("non-integer JSON number")
    return replay(json.loads(raw, object_pairs_hook=pairs,
                            parse_float=forbidden, parse_constant=forbidden))


def summarize(gpu, consumer):
    """Allowlist reviewed fixed facts; drop all private hashes and file paths.

    These saved reports are evidence assertions, not cryptographic proof of
    source association. The private producer/packing checks were reviewed
    externally; the consumer explicitly does not verify that association.
    """
    for key, expected in dict(status="complete", copy_byte_exact=True,
            submitted_native_size_byte_exact=True, scaled_repeats=2,
            scaled_repeat_byte_exact=True, output_words=12441600,
            output_nonzero_low_six_bit_words=0,
            original_el_plane_hashes_match_extraction_and_successful_decoder_expected_planes=True,
            independent_packed_input_word_comparisons=3110400,
            independent_packed_input_words_exact=True,
            executed_packer_source_and_binary_and_original_planes_unchanged=True,
            executed_probe_and_input_and_wrapper_and_libva_libva_drm_libdrm_unchanged=True,
            hardware_engine_verified=False, fractional_quantizer_selected=False,
            production_precision_changed=False, amd_measurement=False).items():
        _exact(gpu.get(key), expected)
    for key, expected in dict(status="complete", raw_samples_exact=12441600,
            fractional_chunks=0, arithmetic_dispatches=191, route="exact-whole-code",
            hardware_source_association_verified_by_this_runner=False,
            independent_arithmetic_reference=False, old_linear_baseline_compared=False).items():
        _exact(consumer.get(key), expected)
    _exact(consumer.get("completion"), dict(kind="arithmetic-frame-complete",
            counts=[8294400,2073600,2073600], diagnostic_queries=0))
    _exact(gpu.get("input_size"), [1920,1080])
    _exact(gpu.get("output_size"), [3840,2160])
    _exact(gpu.get("submitted_request"), FIXED["submitted_request"])
    _exact(gpu.get("scaled_own_client_vpp_engine_delta_ns"), [
        {"render":0,"copy":0,"video":0,"video-enhance":9263956},
        {"render":0,"copy":0,"video":0,"video-enhance":6725784}])
    for field in ("memory_before", "memory_after"):
        memory=consumer[field]
        for k,v in {"memory.max":"536870912", "memory.swap.max":"0",
                    "memory.swap.current":"0"}.items():
            _exact(memory.get(k), v)
        events={}
        for line in memory["memory.events"].splitlines():
            key, value=line.split()
            if key in events or not value.isdecimal():
                raise ValueError("invalid memory events")
            events[key]=int(value)
        for k in ("max", "oom", "oom_kill", "high"):
            _exact(events.get(k), 0)
    _exact(consumer["memory_after"].get("memory.peak"), "245694464")
    r=gpu["resources"]
    _exact(r.get("scaled_memory_peak_snapshot_bytes"), [107167744,106897408])
    for k,v in dict(memory_max_bytes=536870912, memory_swap_max_bytes=0,
            all_observed_swap_current_bytes=0, all_observed_memory_limit_events=0,
            all_observed_oom_events=0, all_observed_oom_kill_events=0).items():
        _exact(r.get(k), v)
    _exact(gpu["driver_identity_after_only"].get("driver_binary_prepost_pin_established"), False)
    p=gpu["public_artifact_pins"]
    result=copy.deepcopy(FIXED)
    result["pins"]=dict(
        engine_sources={k:consumer["source_sha256"][k] for k in SOURCES},
        consumer_source={"native_scaled_surface_frame.py":consumer["runner_sha256"]},
        sdk_library={"native_scaled_surface_chain.so":consumer["private_input_sha256"]["library"]},
        scaler_artifacts={k:p[k+"_sha256"] for k in ("packer_source", "packer_binary",
            "probe_source", "probe_accounting_header", "probe_binary", "wrapper_source")},
        system_libraries={k:p[k+"_sha256"] for k in ("libva", "libva_drm", "libdrm")},
        consumer_runtime={name:consumer["private_runtime_sha256"][path] for name,path in (
            ("python3.12", "/usr/bin/python3.12"),
            ("ld-linux-x86-64.so.2", "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"),
            ("libc.so.6", "/usr/lib/x86_64-linux-gnu/libc.so.6"))},
        driver_after_only={"intel_ihd_driver":gpu["driver_identity_after_only"]["driver_sha256"]})
    return replay(result)
