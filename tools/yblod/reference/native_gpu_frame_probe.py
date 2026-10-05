"""Private prepared-frame sampling diagnostic; public output contains no pixels/RPU.

No decode, resampling, fractional EL policy, film rehash or playback integration.
The existing saved extraction association is checked, not freshly CRC-decoded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess

import colour_metadata as association
import reference
from base_mapping_stage import BaseMappingConfig
from nlq_stage import NLQConfig
from native_gpu_probe import encode
import native_gpu_run as runner
from native_gpu_vectors import GPUVector, expected_stages, width_oracle

CHANNELS = ("Y", "Cb", "Cr")
STAGES = (("mapped", "u16le"), ("residual", "i32le"),
          ("sum", "i32le"), ("reconstructed", "u16le"))
SOURCES = runner.SOURCES + ("native_gpu_frame_probe.py", "colour_metadata.py",
                            "import_rpu.py", "extract_frame.py", "reference.py", "colour_stage.py")


def grid_indices(width, height):
    if any(type(v) is not int or not 1 <= v <= 8192 for v in (width, height)):
        raise ValueError("bounded positive integer raster dimensions required")
    def axis(size):
        n = min(size, 64)
        return (0,) if n == 1 else tuple(i * (size - 1) // (n - 1) for i in range(n))
    return tuple(y * width + x for y in axis(height) for x in axis(width))


def scan_plane(root, filename, count, encoding, indices, expected_hash, *, depth=None):
    """Hash every byte and select <=4096 samples without a full-plane allocation."""
    association._sha(expected_hash)
    root = Path(root).resolve()
    if type(filename) is not str or not filename or Path(filename).is_absolute():
        raise ValueError("relative plane filename required")
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("plane path escapes bundle")
    if encoding not in ("u16le", "i32le") or type(count) is not int or not 1 <= count <= 8192**2:
        raise ValueError("invalid plane encoding/count")
    if (len(indices) > 4096 or tuple(sorted(set(indices))) != tuple(indices)
            or any(type(i) is not int or not 0 <= i < count for i in indices)):
        raise ValueError("bounded ordered unique sample indices required")
    if depth is not None and (encoding != "u16le" or type(depth) is not int or depth not in (8, 10)):
        raise ValueError("native depth must be8/10")
    size, code = (2, "H") if encoding == "u16le" else (4, "i")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode) or initial.st_size != count * size:
            raise ValueError("wrong plane size or nonregular file")
        digest, selected, cursor = hashlib.sha256(), [], 0
        for start in range(0, count, 8192):
            n = min(8192, count - start)
            raw = stream.read(n * size)
            if len(raw) != n * size:
                raise ValueError("truncated plane")
            digest.update(raw)
            values = struct.unpack(f"<{n}{code}", raw)
            if depth is not None and any(v >= 1 << depth for v in values):
                raise ValueError("prepared code exceeds native depth")
            while cursor < len(indices) and indices[cursor] < start + n:
                selected.append(values[indices[cursor] - start])
                cursor += 1
        if (stream.read(1) or association._snapshot(os.fstat(stream.fileno())) != association._snapshot(initial)
                or association._snapshot(path.stat()) != association._snapshot(initial)):
            raise ValueError("plane changed during scan")
    actual = digest.hexdigest()
    if actual != expected_hash:
        raise ValueError("plane hash mismatch")
    return tuple(selected), actual


def prepare_cases(manifest_path, baseline, extraction):
    manifest_path, baseline = Path(manifest_path).resolve(), Path(baseline).resolve()
    manifest, manifest_hash = association._json(manifest_path.parent, manifest_path.name)
    report, report_hash = association._json(baseline, "report.json")
    verified = association.load(baseline, extraction)
    reference.validate(manifest)
    if (report_hash != verified["composer_report_sha256"]
            or report.get("manifest_sha256") != manifest_hash
            or not association._same(manifest, report["input_manifest"])):
        raise ValueError("prepared manifest/baseline association mismatch")
    metadata = manifest["metadata"]
    mapping = BaseMappingConfig.from_mappings(metadata["mappings"], bit_depth=metadata["bl_bit_depth"],
                                               denominator=metadata["coefficient_log2_denom"])
    if not width_oracle(mapping)["supported"]:
        raise ValueError("metadata exceeds GPU width guard; no fallback")
    enabled = not metadata["disable_residual"]
    needs_guide = any(s.method == "mmr" for c in mapping.mappings for s in c.segments)
    if needs_guide and not manifest.get("mmr_luma"):
        raise ValueError("MMR requires the prepared luma guide")
    sizes = ((manifest["width"], manifest["height"]),
             (manifest["width"] // 2, manifest["height"] // 2))
    indices = (grid_indices(*sizes[0]), grid_indices(*sizes[1]), grid_indices(*sizes[1]))
    counts = (sizes[0][0] * sizes[0][1], sizes[1][0] * sizes[1][1], sizes[1][0] * sizes[1][1])
    selected, pins, checks = {}, {}, []
    consumed_names = set()
    for layer in (("bl", "el") if enabled else ("bl",)):
        if set(manifest[layer]["planes"]) != set(CHANNELS):
            raise ValueError("exact three native planes required")
        for component, channel in enumerate(CHANNELS):
            filename = manifest[layer]["planes"][channel]
            role = layer + "_" + channel
            digest = report["input_sha256"][filename]
            args = (manifest_path.parent, filename, counts[component], "u16le", indices[component], digest)
            kwargs = dict(depth=metadata[layer + "_bit_depth"])
            selected[role], pins[role] = scan_plane(*args, **kwargs)
            checks.append((args, kwargs)); consumed_names.add(filename)
    if needs_guide:
        filename = manifest["mmr_luma"]
        args = (manifest_path.parent, filename, counts[1], "u16le", indices[1], report["input_sha256"][filename])
        kwargs = dict(depth=metadata["bl_bit_depth"])
        selected["guide"], pins["guide"] = scan_plane(*args, **kwargs)
        checks.append((args, kwargs)); consumed_names.add(filename)
    if set(report["input_sha256"]) != consumed_names:
        raise ValueError("baseline consumed-plane set differs")
    expected_names = {stage + "_" + channel for channel in CHANNELS for stage, _ in STAGES}
    if set(report["stages"]) != expected_names:
        raise ValueError("exact twelve baseline stages required")
    vectors, baseline_stages = [], []
    for component, channel in enumerate(CHANNELS):
        triplets = (tuple((v, 0, 0) for v in selected["bl_Y"]) if component == 0 else
                    tuple(zip(selected.get("guide", (0,) * len(indices[component])), selected["bl_Cb"], selected["bl_Cr"])))
        nlq = NLQConfig.from_mapping(metadata["nlq"][component], bit_depth=metadata["el_bit_depth"],
                                    denominator=metadata["coefficient_log2_denom"]) if enabled else None
        vector = GPUVector(channel, mapping, component, triplets, nlq,
                           selected["el_" + channel] if enabled else None, metadata["output_bit_depth"])
        stages = []
        for stage, encoding in STAGES:
            role = stage + "_" + channel
            record = report["stages"][role]
            if type(record["samples"]) is not int or record["samples"] != counts[component]:
                raise ValueError("baseline stage sample count mismatch")
            args = (baseline, record["file"], counts[component], encoding, indices[component], record["sha256"])
            samples, pins[role] = scan_plane(*args)
            checks.append((args, {})); stages.append(samples)
        if tuple(stages) != expected_stages(vector):
            raise ValueError("selected baseline stages differ from independent Python arithmetic")
        vectors.append(vector); baseline_stages.append(tuple(stages))
    pins.update(manifest=manifest_hash, baseline_report=report_hash,
                extraction=verified["provenance"]["source_extraction_sha256"],
                rpu_binary=verified["provenance"]["rpu_binary_sha256"],
                rpu_json=verified["provenance"]["rpu_json_sha256"])
    def unchanged():
        for args, kwargs in checks:
            scan_plane(*args, **kwargs)
        if (association._json(manifest_path.parent, manifest_path.name)[1] != manifest_hash
                or not association._same(association.load(baseline, extraction), verified)):
            raise ValueError("prepared/source association changed")
    return tuple(vectors), tuple(baseline_stages), pins, unchanged


def public_summary(private_report):
    """Strict allowlist: never copy private reports, logs, paths, errors or pixels."""
    status = private_report["status"]
    if status not in ("complete", "validated", "failed"):
        raise ValueError("invalid aggregate status")
    result = dict(schema="yblod.native-gpu-frame-summary.v1", status=status,
        scope="Deterministic prepared whole-code sample check; no full-frame GPU, fractional EL, colour, playback or Dolby conformance claim.",
        source_association="saved extracted-RPU hashes/normalization/frame binding; no fresh CRC parse or film rehash",
        sampling="endpoint-inclusive row-major min(64,width) by min(64,height) per component",
        source_sha256={}, input_sha256={}, cases=[])
    for field, allowed in (("source_sha256", set(SOURCES)),
            ("input_sha256", {"manifest", "baseline_report", "extraction", "rpu_binary", "rpu_json", "guide"}
             | {layer + "_" + c for layer in ("bl", "el") for c in CHANNELS}
             | {s + "_" + c for s, _ in STAGES for c in CHANNELS})):
        for key, value in private_report[field].items():
            if key not in allowed:
                raise ValueError("unexpected public hash role")
            result[field][key] = association._sha(value)
    for field in ("binary_sha256", "shader_sha256"):
        result[field] = association._sha(private_report[field])
    for case in private_report["cases"]:
        if case["component"] not in CHANNELS:
            raise ValueError("invalid component label")
        count = case["samples"]
        if type(count) is not int or not 1 <= count <= 4096:
            raise ValueError("invalid sample count")
        item = dict(component=case["component"], samples=count,
                    fixture_sha256=association._sha(case["fixture_sha256"]))
        for key in ("cpu_baseline_gate", "gpu_exact"):
            value = case.get(key, False)
            if type(value) is not bool:
                raise ValueError("strict gate boolean required")
            item[key] = value
        if item["gpu_exact"]:
            item["stage_mismatch_counts"] = [0, 0, 0, 0]
        result["cases"].append(item)
    for key in ("all_cpu_gates_complete", "gpu_attempted"):
        if type(private_report[key]) is not bool:
            raise ValueError("strict aggregate boolean required")
        result[key] = private_report[key]
    names = [case["component"] for case in result["cases"]]
    if len(set(names)) != len(names):
        raise ValueError("duplicate component summaries")
    if status in ("complete", "validated"):
        if (names != list(CHANNELS) or not result["all_cpu_gates_complete"]
                or not all(case["cpu_baseline_gate"] for case in result["cases"])):
            raise ValueError("successful summary requires all three CPU gates")
        if (result["gpu_attempted"] != (status == "complete")
                or any(case["gpu_exact"] != (status == "complete") for case in result["cases"])):
            raise ValueError("successful summary GPU state mismatch")
    resources = private_report.get("resources", {})
    result["resources"] = {k: v for k, v in resources.items()
                           if k in ("charged_peak_bytes", "swap_bytes", "oom_events", "oom_kill_events", "limit_events")
                           and type(v) is int and v >= 0}
    return result


def run(binary, shader, prepared_manifest, baseline, extraction, destination, *,
        device="/dev/dri/renderD128", validate_only=False, require_memory_cap=True):
    if type(validate_only) is not bool or type(require_memory_cap) is not bool:
        raise ValueError("explicit boolean controls required")
    if not runner.re.fullmatch(r"/dev/dri/renderD[0-9]+", device) or not 128 <= int(device.split("renderD")[1]) <= 1048575:
        raise ValueError("explicit render node required")
    snapshot = runner.cgroup_snapshot()
    if require_memory_cap:
        values = snapshot.get("values", {})
        if not (values.get("memory.swap.max") == "0" and values.get("memory.max", "").isdigit()
                and 0 < int(values["memory.max"]) <= 512 * 1024**2):
            raise ValueError("requires enforced <=512MiB memory and zero job swap")
    binary, shader = Path(binary).resolve(strict=True), Path(shader).resolve(strict=True)
    here = Path(__file__).resolve().parent
    source_pins = {name: runner.digest(here / name) for name in SOURCES}
    binary_pin, shader_pin = runner.digest(binary), runner.digest(shader)
    if shader_pin != source_pins["native_gpu_probe.comp"] or not os.access(binary, os.X_OK):
        raise ValueError("reviewed shader and executable required")
    vectors, _, input_pins, unchanged = prepare_cases(prepared_manifest, baseline, extraction)
    root = Path(destination).resolve()
    root.mkdir(mode=0o700, exist_ok=False)
    private = dict(status="failed", source_sha256=source_pins, input_sha256=input_pins,
                   binary_sha256=binary_pin, shader_sha256=shader_pin, cases=[],
                   all_cpu_gates_complete=False, gpu_attempted=False, cgroup_before=snapshot)
    def artifact_pins():
        if runner.digest(binary) != binary_pin or runner.digest(shader) != shader_pin or any(
                runner.digest(here / n) != p for n, p in source_pins.items()):
            raise ValueError("executed artifacts changed")
    def invoke(case, phase, args):
        artifact_pins()
        fixture = root / (case["component"] + ".bin")
        if runner.digest(fixture) != case["fixture_sha256"]:
            raise ValueError("private fixture changed")
        out, err = root / (case["component"] + phase + ".stdout"), root / (case["component"] + phase + ".stderr")
        with out.open("xb") as stdout, err.open("xb") as stderr:
            completed = subprocess.run(args, stdout=stdout, stderr=stderr, timeout=30, check=False)
        artifact_pins()
        if runner.digest(fixture) != case["fixture_sha256"]:
            raise ValueError("private fixture changed during execution")
        raw, _ = association._read(root, out.name)
        report = runner.strict_json(raw)
        case[phase] = dict(exit_status=completed.returncode, report=report)
        if completed.returncode != 0:
            raise ValueError("native diagnostic failed or rejected; no fallback")
        return report
    try:
        for vector in vectors:
            data = encode(vector.mapping, vector.nlq, vector.component, vector.triplets, vector.el_samples, vector.output_depth)
            with (root / (vector.name + ".bin")).open("xb") as stream:
                stream.write(data)
            private["cases"].append(dict(component=vector.name, samples=len(vector.triplets),
                                        fixture_sha256=hashlib.sha256(data).hexdigest()))
        for vector, case in zip(vectors, private["cases"]):
            cpu = invoke(case, "cpu", [str(binary), "--validate", str(root / (vector.name + ".bin"))])
            if not runner.validate_cpu(cpu, vector):
                raise ValueError("width rejection; no fallback")
            case["cpu_baseline_gate"] = True
        unchanged()
        private["all_cpu_gates_complete"] = True
        if not validate_only:
            for vector, case in zip(vectors, private["cases"]):
                private["gpu_attempted"] = True
                gpu = invoke(case, "gpu", [str(binary), device, str(shader), str(root / (vector.name + ".bin"))])
                runner.validate_gpu(gpu, vector)
                case["gpu_exact"] = True
        unchanged(); artifact_pins()
        private["status"] = "validated" if validate_only else "complete"
    except Exception as error:
        private["error"] = dict(type=type(error).__name__, message=str(error))
    after = runner.cgroup_snapshot()
    private["cgroup_after"] = after
    values = after.get("values", {})
    events = dict(line.split() for line in values.get("memory.events", "").splitlines())
    if require_memory_cap:
        before_values = snapshot.get("values", {})
        before_events = dict(line.split() for line in before_values.get("memory.events", "").splitlines())
        memory_ok = (values.get("memory.max") == before_values.get("memory.max")
                     and values.get("memory.swap.max") == "0" and values.get("memory.swap.current") == "0")
        for key in ("max", "oom", "oom_kill"):
            if (not events.get(key, "").isdigit() or not before_events.get(key, "").isdigit()
                    or int(events[key]) != int(before_events[key])):
                memory_ok = False
        if not memory_ok:
            private["status"] = "failed"
            private["resource_guard_failed"] = True
    private["resources"] = {}
    for key, value in (("charged_peak_bytes", values.get("memory.peak")), ("swap_bytes", values.get("memory.swap.current")),
                       ("oom_events", events.get("oom")), ("oom_kill_events", events.get("oom_kill")), ("limit_events", events.get("max"))):
        if value is not None and value.isdigit():
            private["resources"][key] = int(value)
    summary = public_summary(private)
    for filename, value in (("private-report.json", private), ("public-summary.json", summary)):
        with (root / filename).open("x") as stream:
            json.dump(value, stream, indent=2, allow_nan=False); stream.write("\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("binary", "shader", "prepared_manifest", "baseline", "extraction", "destination"):
        parser.add_argument(argument)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({"status": result["status"], "cases": len(result["cases"])}))
    raise SystemExit(result["status"] not in ("complete", "validated"))
