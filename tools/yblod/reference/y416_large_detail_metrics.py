"""Unfitted full-size descending/edge/stripe centre-line diagnostics.

Mirrored sources sum to1016, not1024. Stripe placements test integer source
translation, not independently varied fractional scaler phases. No image pixels
or hashes are revalidated; these scores describe the saved aggregate profiles.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import y416_large_geometry as geometry
import y416_edge_metrics as edges

WORDS = {"Y": "1", "Cb": "0", "Cr": "2"}


def same(actual, expected):
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def profile(sample, component, axis, size):
    key = "center_row_raw_words" if axis == "x" else "center_column_raw_words"
    values = sample["raw_le16_word_positions"][WORDS[component]][key]
    repeats = sample.get("repeat_sha256")
    if (sample.get("repeat_stable") is not True or sample.get("size") != size
            or any(type(v) is not int for v in sample["size"])
            or not same(sample.get("bytes"), size[0] * size[1] * 8)
            or not same(sample.get("profile_sampling"), {"center_row_y": size[1] // 2, "center_column_x": size[0] // 2})
            or not same(sample.get("UYVA_word_indices_hypothesis"), {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3})
            or not isinstance(repeats, list) or not 2 <= len(repeats) <= 4
            or not edges._hash(sample.get("sha256"))
            or any(v != sample["sha256"] for v in repeats)
            or not isinstance(values, list) or len(values) != size[0 if axis == "x" else 1]
            or any(type(v) is not int or not 0 <= v <= 65535 for v in values)):
        raise ValueError("stable raw full-raster profile required")
    return values


def descending_score(raw, component, axis):
    extent = geometry.COMPONENT_SIZES[component][0 if axis == "x" else 1]
    start = extent // 2 - 48
    expansion = Fraction(len(raw), extent)
    first, stop = int(start * expansion) + 32, int((start + 96) * expansion) - 32
    result = {}
    for model in geometry.MODELS:
        errors = {str(i): [] for i in range(4)}
        for i in range(first, stop):
            source = geometry.coordinate(i, len(raw), component, axis, model)
            if not start < source < start + 95:
                raise ValueError("score touches non-affine region")
            expected = 888 - 8 * (source - start)
            errors[str(i % 4)].append(Fraction(raw[i], 64) - expected)
        flat = [v for values in errors.values() for v in values]
        result[model] = {
            "output_index_slice_start_stop": [first, stop], "samples": len(flat),
            "signed_native_code_error_values": [geometry.rational(v) for v in sorted(set(flat))],
            "axis_mod4_signed_native_code_error_values": {
                p: [geometry.rational(v) for v in sorted(set(values))] for p, values in errors.items()},
            "mean_signed_native_code_error": geometry.rational(sum(flat) / len(flat)),
        }
    return result


def mirror_score(ascending, descending):
    if len(ascending) != len(descending):
        raise ValueError("mirror profile geometry mismatch")
    errors = [Fraction(a + d - 64 * 1016, 64) for a, d in zip(ascending, descending)]
    return {"known_source_sum_native_codes": 1016, "full_centre_profile_samples": len(errors),
            "signed_native_code_error_values": [geometry.rational(v) for v in sorted(set(errors))],
            "different_samples": sum(v != 0 for v in errors),
            "interpretation": "mirror-response balance, not a fitted gain/offset or whole-frame comparison"}


def edge_score(raw, baseline, kind):
    if len(raw) != len(baseline) or len(raw) < 128:
        raise ValueError("full-raster baseline geometry mismatch")
    first = len(raw) // 2 - 64
    stop = first + 128
    method = edges.score_step if kind == "step" else edges.score_impulse
    scored = method(raw[first:stop], baseline[first:stop])
    delta = [a - b for a, b in zip(raw, baseline)]
    scored["crop_slice_start_stop_in_full_profile"] = [first, stop]
    scored["full_profile_minimum_native_code_difference"] = geometry.rational(Fraction(min(delta), 64))
    scored["full_profile_maximum_native_code_difference"] = geometry.rational(Fraction(max(delta), 64))
    if kind == "stripe":
        scored["outside_crop_different_samples"] = sum(v != 0 for v in delta[:first] + delta[stop:])
        mass = sum(delta)
        scored["full_profile_signed_mass_raw"] = mass
        scored["full_profile_centroid_output_samples"] = (geometry.rational(
            Fraction(sum(i * v for i, v in enumerate(delta)), mass)) if mass > 0 else None)
    return scored


def translation_score(first, second, pixels):
    if len(first) != len(second) or not 0 < pixels < len(first):
        raise ValueError("invalid declared translation")
    errors = [Fraction(second[i] - first[i - pixels], 64) for i in range(pixels, len(first))]
    return {"expected_output_pixel_translation": pixels,
            "overlap_samples": len(errors), "different_samples": sum(v != 0 for v in errors),
            "signed_native_code_error_values": [geometry.rational(v) for v in sorted(set(errors))],
            "interpretation": "integer input-shift covariance on overlap; not a new fractional phase test"}


def analyse_report(report, ascending=None):
    if (report.get("schema") != "yblod.hardware-y416-large-detail.v1"
            or report.get("status") != "complete"
            or report.get("all_sameformat_p010_gates_complete") is not True):
        raise ValueError("complete gated full-size detail report required")
    corpus = report.get("corpus")
    if corpus not in ("descending", "edges", "stripes"):
        raise ValueError("unknown detail corpus")
    if (not same(report.get("input_size"), [1920, 1080])
            or not same(report.get("output_size"), [3840, 2160])):
        raise ValueError("full-size source/output declarations required")
    if ascending is not None and (ascending.get("schema") != "yblod.hardware-y416-large.v1"
            or ascending.get("status") != "complete"
            or ascending.get("binary_sha256") != report.get("binary_sha256")):
        raise ValueError("complete same-binary ascending report required")
    output = {"schema": "yblod.y416-large-detail-metrics.v1", "status": "complete", "corpus": corpus,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "helper_sha256": {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                                 for m in (geometry, edges)}, "results": {},
              "interpretation": "saved centre-line diagnostics, not whole-frame acceptance, filter identification, correction or Dolby conformance"}
    for stage, size in (("native", [1920, 1080]), ("scaled", [3840, 2160])):
        scored = output["results"][stage] = {}
        cases = report["results"][stage]
        for component in WORDS:
            for axis in ("x", "y"):
                suffixes = ("descending",) if corpus == "descending" else (("step",) if corpus == "edges" else ("stripe-phase0", "stripe-phase1"))
                placement_profiles = []
                for suffix in suffixes:
                    case = f"{component}-{axis}-{suffix}"
                    spec = report["inputs"][case]["case_spec"]
                    if spec.get("component") != component or spec.get("axis") != axis:
                        raise ValueError("isolated component/axis declaration differs")
                    if (not same(spec.get("native_component_sizes"), geometry.COMPONENT_SIZES)
                            or not same(spec.get("input_size"), geometry.INPUT)
                            or not same(spec.get("baseline_code"), 512)):
                        raise ValueError("canonical source grids and baseline required")
                    raw = profile(cases[case], component, axis, size)
                    extent = geometry.COMPONENT_SIZES[component][0 if axis == "x" else 1]
                    if corpus == "descending":
                        required = {"kind": "descending", "signed_slope": -8,
                                    "native_band_length": 96, "band_start_native": extent // 2 - 48,
                                    "band_stop_native_exclusive": extent // 2 + 48,
                                    "band_first_code": 888, "band_last_code": 128, "source_center_code": 504,
                                    "source_center_native_index": extent // 2, "phase": None,
                                    "source_index_offset": None, "increment_code": 0, "change_native_index": None}
                        if any(type(spec.get(k)) is not type(v) or spec[k] != v for k, v in required.items()):
                            raise ValueError("canonical mirrored source band required")
                        scored[case] = {"geometry_hypotheses": descending_score(raw, component, axis)}
                        if ascending is not None:
                            asc_spec = ascending["inputs"][f"{component}-{axis}-ascending"]["case_spec"]
                            asc_required = {"component": component, "axis": axis, "signed_slope": 8,
                                            "baseline_code": 512, "native_band_length": 96,
                                            "band_start_native": extent // 2 - 48,
                                            "band_stop_native_exclusive": extent // 2 + 48,
                                            "source_center_native_index": extent // 2,
                                            "band_first_code": 128, "band_last_code": 888,
                                            "native_component_sizes": geometry.COMPONENT_SIZES, "input_size": geometry.INPUT}
                            if not same(asc_spec, asc_required):
                                raise ValueError("canonical matching ascending fixture required")
                            asc = profile(ascending["results"][stage][f"{component}-{axis}-ascending"], component, axis, size)
                            scored[case]["mirror_balance"] = mirror_score(asc, raw)
                    else:
                        kind = "step" if corpus == "edges" else "stripe"
                        phase = None if kind == "step" else int(suffix[-1])
                        required = {"kind": kind, "baseline_code": 512, "increment_code": 64,
                                    "change_native_index": extent // 2 + (phase or 0), "phase": phase,
                                    "source_index_offset": phase, "signed_slope": 0,
                                    "native_band_length": None, "band_start_native": None,
                                    "band_stop_native_exclusive": None, "source_center_native_index": extent // 2}
                        if any(type(spec.get(k)) is not type(v) or spec[k] != v for k, v in required.items()):
                            raise ValueError("canonical bounded stimulus required")
                        base = profile(cases["neutral"], component, axis, size)
                        scored[case] = edge_score(raw, base, kind)
                        placement_profiles.append(raw)
                if corpus == "stripes":
                    pixels = size[0 if axis == "x" else 1] // extent
                    scored[f"{component}-{axis}-placement-translation"] = translation_score(*placement_profiles, pixels)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ascending-report", type=Path)
    args = parser.parse_args()
    data = args.report.read_bytes()
    asc_data = args.ascending_report.read_bytes() if args.ascending_report else None
    output = analyse_report(json.loads(data), json.loads(asc_data) if asc_data else None)
    output["input_report_sha256"] = hashlib.sha256(data).hexdigest()
    if asc_data: output["ascending_report_sha256"] = hashlib.sha256(asc_data).hexdigest()
    with args.output.open("x") as handle:
        json.dump(output, handle, indent=2, sort_keys=True)
        handle.write("\n")
