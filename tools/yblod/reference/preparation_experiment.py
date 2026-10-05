#!/usr/bin/env python3
"""Four native chroma-phase policies, with unchanged scaling/composition/output.

The parent uses only the standard library. Each heavy stage runs in a separate
sequential child process so NumPy/libc allocations cannot accumulate between
stages. Run the whole command under the externally configured memory limit.
New stage bundles remain private; only aggregate reports should be published.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from extract_frame import digest, save_json
from import_rpu import normalize
from reference import CHANNELS, validate
from summarize_cases import checked, read_json

CASES = (("linear-both", "linear", "linear"),
         ("cubic-bl-only", "cubic128", "linear"),
         ("cubic-el-only", "linear", "cubic128"),
         ("cubic-both", "cubic128", "cubic128"))
CHUNK_BYTES = 1024 * 1024
STRIP_ROWS = 32
FIXED_OUTPUT = ("identity", "width", "height", "active_rectangle", "policy",
                "chroma_expansion", "pq_domain", "quantization", "transport_sampling",
                "target_ycc", "target_lms", "target_offset", "source_dm", "rpu_sha256",
                "implementation_sha256", "numpy_version")


def stage_file(root, record, size):
    root = Path(root).resolve()
    name = record["file"]
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError("stage filename must be relative")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.stat().st_size != size or digest(path) != record["sha256"]:
        raise ValueError("stage integrity failed: " + name)
    return path


def effective_filters(details):
    filters = details.get("phase_filters")
    if filters is None:
        filters = {layer: details["phase_filter"] for layer in ("bl", "el")}
    if set(filters) != {"bl", "el"} or any(value not in ("linear", "cubic128") for value in filters.values()):
        raise ValueError("invalid per-layer preparation filters")
    return filters


def prepared_bundle(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "frame.json")
    validate(manifest)
    details = manifest["preparation_details"]
    effective_filters(details)
    if (manifest["format"] != "yuv420p-u16le-lsb" or manifest["transfer"] != "pq"
            or manifest["chroma_location"] != "left" or details["output_chroma_location"] != "left"):
        raise ValueError("unsupported prepared geometry")
    paths = {}
    for name, record in details["stages"].items():
        width, height = record["width"], record["height"]
        if any(type(v) is not int or v <= 0 for v in (width, height)):
            raise ValueError("invalid prepared stage dimensions")
        paths[name] = stage_file(directory, record, width*height*2)
    for layer in ("bl", "el"):
        for channel in CHANNELS:
            name = layer + "_" + channel
            factor = 1 if channel == "Y" else 2
            record = details["stages"][name]
            if (record["width"], record["height"]) != (manifest["width"]//factor, manifest["height"]//factor):
                raise ValueError("prepared component geometry mismatch")
            if manifest[layer]["planes"][channel] != record["file"]:
                raise ValueError("prepared component stage binding mismatch")
    guide = details["stages"]["mmr_luma"]
    if (guide["width"], guide["height"], guide["file"]) != (manifest["width"]//2, manifest["height"]//2, manifest["mmr_luma"]):
        raise ValueError("MMR guide geometry mismatch")
    job_path = directory / "el-scaling-job.json"
    if digest(job_path) != details["el_scaling_job_sha256"]:
        raise ValueError("EL scaling contract changed")
    job = read_json(job_path)
    if (job["schema"] != "yblod.el-scaling-job.v1" or job["backend"] != "cpu-ccm-annex-b-reference"
            or job["preparation_before_scaling"] != effective_filters(details)["el"]
            or job["does_not_apply_rpu_or_combine_layers"] is not True):
        raise ValueError("unexpected EL scaling contract")
    identity = {key: manifest["el"][key] for key in ("frame_id", "pts", "time_base")}
    if job["identity"] != identity or job["geometry"] != details["geometry_assumption"]:
        raise ValueError("EL scaler identity/geometry binding mismatch")
    if job["source_native_chroma_location"] != details["native_chroma_locations"]["el"]:
        raise ValueError("EL scaler native chroma location differs")
    for side, divisor in (("input", 2), ("output", 1)):
        expected = {"width": manifest["width"]//divisor, "height": manifest["height"]//divisor,
                    "bit_depth": manifest["metadata"]["el_bit_depth"],
                    "chroma_location": "left", "format": "yuv420p-u16le-lsb"}
        if any(job[side][key] != value for key, value in expected.items()):
            raise ValueError("EL scaler declared format/depth/geometry differs")
    for channel, record in job["input"]["planes"].items():
        if channel not in CHANNELS:
            raise ValueError("unexpected EL scaler component")
        factor = 1 if channel == "Y" else 2
        if (record["width"], record["height"]) != (job["input"]["width"]//factor, job["input"]["height"]//factor):
            raise ValueError("EL scaler input dimensions differ")
        paths["scaler_input_" + channel] = stage_file(directory, record, record["width"]*record["height"]*2)
    if set(job["input"]["planes"]) != set(CHANNELS):
        raise ValueError("missing EL scaler input")
    if job["output"]["planes"] != {c: details["stages"]["el_" + c] for c in CHANNELS}:
        raise ValueError("EL scaler output binding mismatch")
    return manifest, paths


def composer_bundle(directory, prepared, manifest):
    directory, prepared = Path(directory), Path(prepared)
    report = read_json(directory / "report.json")
    if (report["schema"] != "yblod.composer-result.v1" or report["status"] != "complete"
            or report["input_manifest"] != manifest
            or report["manifest_sha256"] != digest(prepared / "frame.json")):
        raise ValueError("composer/prepared provenance mismatch")
    for name, checksum in report["input_sha256"].items():
        path = (prepared / name).resolve()
        if not path.is_relative_to(prepared.resolve()) or digest(path) != checksum:
            raise ValueError("composer input changed")
    paths = {}
    expected = {stage + "_" + channel for stage in ("mapped", "residual", "sum", "reconstructed") for channel in CHANNELS}
    if set(report["stages"]) != expected:
        raise ValueError("incomplete composer stages")
    for name, record in report["stages"].items():
        stage, channel = name.rsplit("_", 1)
        count = manifest["width"]*manifest["height"]//(1 if channel == "Y" else 4)
        if record["samples"] != count:
            raise ValueError("composer stage dimensions differ")
        paths[name] = stage_file(directory, record, count*(4 if stage in ("sum", "residual") else 2))
    return report, paths


def output_bundle(directory, result, manifest):
    info, comparison, provenance = checked(directory, "direct")
    if ((info["width"], info["height"]) != (manifest["width"], manifest["height"])
            or info["identity"] != {key: manifest["bl"][key] for key in ("frame_id", "pts", "time_base")}
            or info["composer_report_sha256"] != digest(Path(result) / "report.json")
            or info["chroma_expansion"] != "bilinear-left-edge-replicated-float64"
            or info["transport_sampling"] != "P/T co-sited at even x; top-down RGB8"):
        raise ValueError("output geometry/provenance differs")
    paths = {}
    for name, record in info["stages"].items():
        if record["shape"] != [info["height"], info["width"], 3]:
            raise ValueError("output stage dimensions differ")
        suffix = Path(record["file"]).suffix
        if suffix not in (".f32le", ".u16le", ".rgb8"):
            raise ValueError("unsupported output stage storage")
        paths[name] = stage_file(directory, record, info["width"]*info["height"]*3*{
            ".f32le": 4, ".u16le": 2, ".rgb8": 1}[suffix])
    return info, comparison, provenance, paths


def byte_identical(first, second):
    total = 0
    with Path(first).open("rb") as a, Path(second).open("rb") as b:
        while True:
            left, right = a.read(CHUNK_BYTES), b.read(CHUNK_BYTES)
            if left != right:
                raise ValueError(f"baseline byte mismatch: {Path(first).name}, at or after byte {total}")
            if not left:
                return total
            total += len(left)


def equal_bundles(first, second):
    if set(first) != set(second):
        raise ValueError("baseline stage set mismatch")
    return {name: byte_identical(first[name], second[name]) for name in first}


def factorial_controls(name, prepared, composed, baseline_prepared, baseline_composed, previous):
    """Exact stage invariants; final nonlinear transport differences need not add."""
    checks = {}
    def compare(label, first, second):
        checks[label] = byte_identical(first, second)
    for stage in ("bl_Y", "el_Y", "el_Y_vertical", "scaler_input_Y", "mmr_luma"):
        compare(stage, baseline_prepared[stage], prepared[stage])
    compare("reconstructed_Y", baseline_composed["reconstructed_Y"], composed["reconstructed_Y"])
    if name == "cubic-bl-only":
        for stage in baseline_prepared:
            if stage.startswith("el_") or stage.startswith("scaler_input_"):
                compare(stage, baseline_prepared[stage], prepared[stage])
        for channel in CHANNELS:
            stage = "residual_" + channel
            compare(stage, baseline_composed[stage], composed[stage])
    elif name == "cubic-el-only":
        for stage in baseline_prepared:
            if stage.startswith("bl_") or stage == "mmr_luma":
                compare(stage, baseline_prepared[stage], prepared[stage])
        for channel in CHANNELS:
            stage = "mapped_" + channel
            compare(stage, baseline_composed[stage], composed[stage])
    elif name == "cubic-both":
        for kind, source_case in (("mapped", "cubic-bl-only"), ("residual", "cubic-el-only")):
            for channel in CHANNELS:
                stage = kind + "_" + channel
                compare(stage + "_equals_" + source_case, previous[source_case][stage], composed[stage])
    return checks


def source_binding(extraction, manifest, capture, identity_file, comparison, expected_visible_frame):
    extraction = Path(extraction)
    ex = read_json(extraction / "extraction.json")
    instructions = read_json(extraction / "composition.json")
    verification = read_json(extraction / "verification/verification.json")
    details = manifest["preparation_details"]
    ex_hash, composition_hash = digest(extraction / "extraction.json"), digest(extraction / "composition.json")
    if (ex["schema"] != "yblod.extracted-frame.v1" or ex["status"] != "complete"
            or ex["rpu_matches_source_packet_and_global_index"] is not True
            or verification["status"] != "complete" or verification["metadata_normalization_exact"] is not True
            or verification["extraction_sha256"] != ex_hash or verification["composition_sha256"] != composition_hash
            or instructions["source_extraction_sha256"] != ex_hash
            or details["source_extraction_sha256"] != ex_hash
            or details["source_composition_sha256"] != composition_hash
            or details["source_verification_sha256"] != digest(extraction / "verification/verification.json")
            or digest(extraction / "rpu.json") != ex["rpu_json_sha256"]
            or digest(extraction / "frame.rpu.bin") != ex["rpu_sha256"]):
        raise ValueError("native extraction/instructions verification mismatch")
    identity = {"frame_id": f"{ex['source_sha256']}:{ex['source_packet_index_zero_based']}",
                "pts": ex["pts"], "time_base": ex["time_base"]}
    rpu = read_json(extraction / "rpu.json")
    if (normalize(rpu, identity) != manifest["metadata"] or instructions["metadata"] != manifest["metadata"]
            or rpu["header"]["chroma_resampling_explicit_filter_flag"]):
        raise ValueError("unsupported or changed RPU instructions")
    supplied = read_json(identity_file)
    if "overlay_present" in supplied and supplied["overlay_present"] is not False:
        raise ValueError("capture identity explicitly reports an overlay or ambiguous overlay status")
    if (type(expected_visible_frame) is not int or expected_visible_frame < 0
            or supplied["visible_frame_number"] != expected_visible_frame
            or identity["frame_id"] != f"{supplied['source_sha256']}:{supplied['visible_frame_number']}"
            or identity["pts"]*identity["time_base"][0]*1000000 != supplied["pts_us"]*identity["time_base"][1]
            or comparison["identity"] != identity
            or comparison["capture_sha256"] != digest(capture)
            or comparison["identity_file_sha256"] != digest(identity_file)):
        raise ValueError("capture/visible-counter/source association mismatch")
    native_hashes = {}
    for layer in ("bl", "el"):
        info = ex["layers"][layer]
        if (info["chroma_location"] not in ("left", "topleft") or info["stream"]["color_transfer"] != "smpte2084"
                or details["native_chroma_locations"][layer] != info["chroma_location"]
                or verification["layers"][layer]["single_and_four_thread_decodes_identical"] is not True):
            raise ValueError("native layer geometry/verification mismatch")
        for channel in CHANNELS:
            record = info["planes"][channel]
            factor = 1 if channel == "Y" else 2
            stage_file(extraction, record, info["width"]//factor * (info["height"]//factor)*2)
            native_hashes[record["file"]] = record["sha256"]
    if (native_hashes != details["source_plane_sha256"]
            or (ex["layers"]["bl"]["width"], ex["layers"]["bl"]["height"]) != (manifest["width"], manifest["height"])
            or (ex["layers"]["el"]["width"]*2, ex["layers"]["el"]["height"]*2) != (manifest["width"], manifest["height"])):
        raise ValueError("native input plane/scaling contract mismatch")
    return identity


def command(script, *arguments):
    return [sys.executable, str(Path(__file__).resolve().with_name(script)), *map(str, arguments)]


def run_stage(argv, log):
    # Redirect even failures to a bounded-on-RAM local log, never PIPE full output.
    with Path(log).open("x") as stream:
        subprocess.run(argv, check=True, stdout=stream, stderr=subprocess.STDOUT)


def prepare_command(extraction, output, bl, el):
    if bl not in ("linear", "cubic128") or el not in ("linear", "cubic128"):
        raise ValueError("invalid experiment layer policy")
    result = command("prepare_frame.py", extraction, output, "--phase-filter", "linear")
    if (bl, el) != ("linear", "linear"):
        result += ["--bl-phase-filter", bl, "--el-phase-filter", el]
    return result


def tunnel_delta(baseline, candidate):
    """Worker-only NumPy: generated RGB8, NEVER CoreELEC memory-unswizzling."""
    import numpy as np
    from compare_output import unpack_rgb
    from diagnose_frame import accumulate, finish, new_total, read_strip
    before, _, _ = checked(baseline, "direct")
    after, _, _ = checked(candidate, "direct")
    for key in FIXED_OUTPUT:
        if before[key] != after[key]:
            raise ValueError("delta outputs differ in fixed field: " + key)
    l, t, r, b = before["active_rectangle"]
    totals = {c: {g: new_total() for g in ("all", "even_row", "odd_row")} for c in ("I", "P", "T")}
    with (Path(baseline) / before["stages"]["unembedded_tunnel"]["file"]).open("rb") as first, \
            (Path(candidate) / after["stages"]["unembedded_tunnel"]["file"]).open("rb") as second:
        for start in range(t, b, STRIP_ROWS):
            stop = min(start+STRIP_ROWS, b)
            decoded = [unpack_rgb(*np.moveaxis(read_strip(stream, start, stop, before["width"], "u1"), -1, 0)) for stream in (first, second)]
            rows = np.arange(start, stop)
            for c, plane, indices in (("I", 0, slice(l, r)), ("P", 1, slice(l, r, 2)), ("T", 1, slice(l+1, r, 2))):
                delta = decoded[1][plane][:, indices].astype(np.int64) - decoded[0][plane][:, indices]
                for group, values in (("all", delta), ("even_row", delta[rows % 2 == 0]), ("odd_row", delta[rows % 2 == 1])):
                    accumulate(totals[c][group], values)
    for c, groups in totals.items():
        expected = (r-l)*(b-t)//(1 if c == "I" else 2)
        if groups["all"]["samples"] != expected or groups["even_row"]["samples"]+groups["odd_row"]["samples"] != expected:
            raise ValueError("delta masks do not partition active picture")
    return {"direction": "candidate minus newly regenerated linear-both baseline", "row_parity": "global picture rows",
            "active_rectangle": [l, t, r, b], "processing_strip_rows": STRIP_ROWS,
            "channels": {c: {g: finish(value) for g, value in groups.items()} for c, groups in totals.items()}}


def experiment(extraction, baseline_prepared, baseline_result, baseline_output, capture, identity_file,
               output, expected_visible_frame):
    wrapper_sha256 = digest(Path(__file__))
    extraction, baseline_prepared, baseline_result, baseline_output, capture, identity_file, output = [
        Path(p).resolve() for p in (extraction, baseline_prepared, baseline_result, baseline_output, capture, identity_file, output)]
    manifest, old_prepared = prepared_bundle(baseline_prepared)
    if effective_filters(manifest["preparation_details"]) != {"bl": "linear", "el": "linear"}:
        raise ValueError("saved baseline must use linear preparation for both layers")
    old_report, old_reconstructed = composer_bundle(baseline_result, baseline_prepared, manifest)
    old_output, old_comparison, old_provenance, old_output_files = output_bundle(baseline_output, baseline_result, manifest)
    identity = source_binding(extraction, manifest, capture, identity_file, old_comparison, expected_visible_frame)
    if (old_output["rpu_sha256"] != digest(extraction / "rpu.json")
            or old_output["source_dm"] != read_json(extraction / "rpu.json")["vdr_dm_data"]):
        raise ValueError("baseline output uses different source colour instructions")
    output.mkdir(parents=True, exist_ok=False)
    baseline_exact, variants, prior_composed, implementation_pins = {}, {}, {}, None
    new_baseline = output / CASES[0][0] / "output"
    fixed_preparation = ("source_extraction_sha256", "source_composition_sha256", "source_verification_sha256",
                         "source_plane_sha256", "native_chroma_locations", "output_chroma_location",
                         "specification_pdf_sha256", "geometry_assumption")
    for name, bl, el in CASES:
        if digest(Path(__file__)) != wrapper_sha256:
            raise ValueError("experiment wrapper changed while running")
        case = output / name
        case.mkdir()
        prepared, result, rendered = case / "prepared", case / "result", case / "output"
        run_stage(prepare_command(extraction, prepared, bl, el), case / "prepare.log")
        current, prepared_files = prepared_bundle(prepared)
        if effective_filters(current["preparation_details"]) != {"bl": bl, "el": el}:
            raise ValueError("preparation did not apply requested layer policy")
        for key in ("schema", "width", "height", "format", "transfer", "chroma_location", "metadata"):
            if current[key] != manifest[key]:
                raise ValueError("prepared fixed contract changed: " + key)
        for key in fixed_preparation:
            if current["preparation_details"][key] != manifest["preparation_details"][key]:
                raise ValueError("preparation source/geometry changed: " + key)
        # Luma guide, BL luma and all EL luma scaling must remain byte-exact.
        for stage in ("bl_Y", "el_Y", "el_Y_vertical", "scaler_input_Y", "mmr_luma"):
            byte_identical(old_prepared[stage], prepared_files[stage])
        if name == CASES[0][0]:
            baseline_exact["prepared_stages_verified_bytes"] = equal_bundles(old_prepared, prepared_files)
        run_stage(command("reference.py", prepared / "frame.json", result), case / "compose.log")
        report, reconstructed_files = composer_bundle(result, prepared, current)
        if report["implementation_sha256"] != old_report["implementation_sha256"]:
            raise ValueError("composer implementation changed from saved baseline")
        if name == CASES[0][0]:
            baseline_exact["composer_stages_verified_bytes"] = equal_bundles(old_reconstructed, reconstructed_files)
        stage_controls = factorial_controls(name, prepared_files, reconstructed_files,
                                            old_prepared, old_reconstructed, prior_composed)
        prior_composed[name] = reconstructed_files
        run_stage(command("output_frame.py", result, extraction, rendered, "--policy", "direct"), case / "render.log")
        run_stage(command("compare_output.py", rendered, capture, identity_file, "--report", rendered / "sk4.json"), case / "compare.log")
        info, comparison, _, output_files = output_bundle(rendered, result, current)
        for key in FIXED_OUTPUT:
            if info[key] != old_output[key]:
                raise ValueError("fixed output setting changed: " + key)
        for key in ("capture_sha256", "identity_file_sha256", "identity_basis"):
            if comparison[key] != old_comparison[key]:
                raise ValueError("capture comparison association changed: " + key)
        if name == CASES[0][0]:
            baseline_exact["tunnel_verified_bytes"] = byte_identical(old_output_files["unembedded_tunnel"], output_files["unembedded_tunnel"])
        run_stage(command("transport_precision.py", rendered, capture, "--report", case / "precision.json"), case / "precision.log")
        precision = read_json(case / "precision.json")
        if (precision["status"] != "complete" or precision["identity"] != identity
                or precision["capture_sha256"] != old_comparison["capture_sha256"]
                or precision["active_rectangle"] != old_output["active_rectangle"]
                or precision["metadata"] != {"packets": 2, "copies_per_packet": 3, "all_crc_valid": True, "copies_identical": True}):
            raise ValueError("precision audit framing/identity mismatch")
        pins = {"preparer_sha256": current["preparation_details"]["preparer_sha256"],
                "prepare_numpy_version": current["preparation_details"]["numpy_version"],
                "composer_sha256": report["implementation_sha256"],
                "comparison_sha256": comparison["implementation_sha256"],
                "precision_sha256": precision["implementation"]["sha256"],
                "precision_helpers": precision["helper_implementations"], "precision_runtime": precision["runtime"]}
        if implementation_pins is None:
            implementation_pins = pins
        elif pins != implementation_pins:
            raise ValueError("implementation/runtime changed between experiment cases")
        run_stage(command(Path(__file__).name, "--delta-worker", new_baseline, rendered, case / "delta.json"), case / "delta.log")
        variants[name] = {"phase_filters": {"bl": bl, "el": el}, "comparisons": comparison["channels"],
                          "factorial_stage_verified_bytes": stage_controls,
                          "minus_baseline": read_json(case / "delta.json"),
                          "even_minus_odd_signed_mean_gaps": precision["even_minus_odd_signed_mean_gaps"],
                          "preparation_operations": current["preparation_details"]["operations"],
                          "reports": {str(path.relative_to(output)): digest(path) for path in
                                      (prepared / "frame.json", result / "report.json", rendered / "output.json",
                                       rendered / "sk4.json", case / "precision.json", case / "delta.json")}}
    if digest(Path(__file__)) != wrapper_sha256:
        raise ValueError("experiment wrapper changed while running")
    final = {"schema": "yblod.preparation-experiment.v1", "status": "complete", "identity": identity,
             "capture_sha256": old_comparison["capture_sha256"], "identity_file_sha256": digest(identity_file),
             "supplied_capture_identity": read_json(identity_file),
             "identity_basis": old_comparison["identity_basis"], "baseline_source": old_provenance,
             "active_rectangle": old_output["active_rectangle"], "baseline_byte_verification": baseline_exact,
             "variants": variants, "implementation_sha256": wrapper_sha256,
             "pinned_stage_implementations": implementation_pins,
             "execution": "sequential child processes; external memory limit required; no hardware jobs",
             "held_fixed": ["native decoded layers and RPU", "phase conversion before EL scaling",
                            "integer rounding/bounds", "CCM annex B EL scaling", "MMR guide and composer",
                            "final bilinear expansion, direct colour conversion, packing and active-area mask"],
             "limitations": ["Tests only native top-left-to-left chroma preparation kernel sensitivity.",
                             "Does not test scaling before versus after inverse mapping/residual reconstruction, or fused processing.",
                             "Does not evaluate Intel/AMD hardware scalers or real-time performance.",
                             "Mapped/residual stage isolation is checked exactly; final transport effects need not add because subsequent conversion and quantization are nonlinear.",
                             "Cubic overshoot uses existing declared phase-stage bounds; no new limiting or fitted adjustments.",
                             "Any unsupported geometry/filter, out-of-depth annex B result, failed stage or baseline mismatch aborts; no skipped variants.",
                             "Matching SK4 transport codes does not establish Dolby compliance or displayed colour accuracy.",
                             "Captured-frame association and DMA synchronization limitations remain those of the supplied capture.",
                             "Generated raw/intermediate pictures stay private; publish only aggregate reports, not stage bundles."]}
    save_json(output / "experiment.json", final)
    return final


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--delta-worker"]:
        if len(argv) != 4:
            raise ValueError("delta worker requires baseline candidate report")
        save_json(Path(argv[3]), tunnel_delta(Path(argv[1]), Path(argv[2])))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("extraction", "baseline_prepared", "baseline_result", "baseline_output", "capture", "identity_file", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--expected-visible-frame", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        experiment(**vars(args))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"preparation experiment: {error}\n")
    print(args.output / "experiment.json")


if __name__ == "__main__":
    main()
