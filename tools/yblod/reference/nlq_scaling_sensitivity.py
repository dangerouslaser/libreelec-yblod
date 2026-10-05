"""Exact rational sensitivity of the standalone NLQ arithmetic, not DV conformance.

The reference composer accepts integer EL codes. Applying its pre-shift algebra
to fractions is an explicitly hypothetical extension, NOT a normative rule for
Y416 or an emulation of the finite-float playback shader. Raw words retain all
bits through Fraction(word, 64). No picture, colour conversion or fitted offset.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import reference
import y416_large_geometry as geometry

PARAMETERS = {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1048576}
SPEC = reference.SPEC


def rational(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def exact(value, name):
    if type(value) not in (int, Fraction):
        raise ValueError(f"{name} must be an integer or Fraction, never float/bool")
    return Fraction(value)


def validate(parameters, bit_depth, denominator):
    if type(bit_depth) is not int or bit_depth not in (8, 10):
        raise ValueError("EL bit depth must be 8 or 10")
    reference.integer(denominator, "coefficient denominator", bit_depth + 5, 32)
    if not isinstance(parameters, dict) or set(parameters) != {"offset", "slope", "threshold", "maximum"}:
        raise ValueError("exactly offset/slope/threshold/maximum required")
    reference.integer(parameters["offset"], "offset", 0, (1 << bit_depth) - 1)
    for name in ("slope", "threshold", "maximum"):
        reference.integer(parameters[name], name, 0, (2 << denominator) - 1)


def formula_extension(sample, parameters=PARAMETERS, bit_depth=10, denominator=23):
    """Pre-final-shift algebra in 16-bit residual-code units; fractional model only.

    Clip the accumulator at the same stage as reference.inverse_el. Do not add
    a dead-zone clamp: for fractional distances under half a code this algebra
    can reverse sign. That is reported, not corrected or called normative.
    """
    validate(parameters, bit_depth, denominator)
    sample = exact(sample, "sample")
    if not 0 <= sample <= (1 << bit_depth) - 1:
        raise ValueError("sample outside declared EL code range; no implicit clamp")
    distance = sample - parameters["offset"]
    if not distance:
        return Fraction(0)
    sign = 1 if distance > 0 else -1
    gain = 1 << (10 - bit_depth)
    accumulator = ((2 * distance - sign) * parameters["slope"]
                   + 2 * sign * parameters["threshold"]) * gain
    limit = 2 * gain * parameters["maximum"]
    accumulator = min(limit, max(-limit, accumulator))
    return Fraction(accumulator) / (1 << (denominator - 5 - bit_depth))


def floor_extension(sample, parameters=PARAMETERS, bit_depth=10, denominator=23):
    """Hypothetical fractional-input extension with the reference's final floor."""
    value = formula_extension(sample, parameters, bit_depth, denominator)
    return value.numerator // value.denominator


def reconstruct_extension(mapped, residual, output_depth=12):
    reference.integer(mapped, "mapped 16-bit code", 0, 65535)
    if type(output_depth) is not int or output_depth not in (10, 12):
        raise ValueError("output depth must be 10 or 12")
    residual = exact(residual, "residual")
    step = 1 << (16 - output_depth)
    value = (mapped + residual + step // 2) / step
    return min((1 << output_depth) - 1, max(0, value.numerator // value.denominator))


def score_pair(raw_word, expected_sample, *, mapped=32768, parameters=PARAMETERS,
               bit_depth=10, denominator=23):
    if bit_depth != 10:
        raise ValueError("word/64 transport convention is declared only for 10-bit EL")
    reference.integer(raw_word, "raw Y416 colour word", 0, 65535)
    sample = Fraction(raw_word, 64)
    expected_sample = exact(expected_sample, "expected sample")
    actual = formula_extension(sample, parameters, bit_depth, denominator)
    expected = formula_extension(expected_sample, parameters, bit_depth, denominator)
    actual_floor, expected_floor = (v.numerator // v.denominator for v in (actual, expected))
    reference.integer(mapped, "mapped 16-bit code", 0, 65535)
    return {
        "raw_word": raw_word, "sample_native_codes": rational(sample),
        "expected_native_codes": rational(expected_sample),
        "sample_error_native_codes": rational(sample - expected_sample),
        "fractional_input_present": sample.denominator != 1 or expected_sample.denominator != 1,
        "normative_fractional_result": None,
        "actual_extension_residual": rational(actual), "expected_extension_residual": rational(expected),
        "extension_residual_error_16bit_units": rational(actual - expected),
        "extension_error_unrounded_12bit_units": rational((actual - expected) / 16),
        "actual_extension_floor": actual_floor, "expected_extension_floor": expected_floor,
        "floored_extension_error_16bit_units": actual_floor - expected_floor,
        "neutral_relation": {"expected": (expected_sample > parameters["offset"]) - (expected_sample < parameters["offset"]),
                             "actual": (sample > parameters["offset"]) - (sample < parameters["offset"])},
        "synthetic_mapped_code": mapped,
        "synthetic_reconstructed_12bit_actual": reconstruct_extension(mapped, actual),
        "synthetic_reconstructed_12bit_expected": reconstruct_extension(mapped, expected),
        "integer_reference_actual": (reference.inverse_el(int(sample), parameters, bit_depth, denominator)
                                     if sample.denominator == 1 else None),
        "integer_reference_expected": (reference.inverse_el(int(expected_sample), parameters, bit_depth, denominator)
                                       if expected_sample.denominator == 1 else None),
    }


def _histogram(values):
    counts = Counter(values)
    return [{"value": rational(value), "count": counts[value]} for value in sorted(counts)]


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("strict lowercase SHA256 declaration required")
    return value


def analyse_measured(value):
    """Use real saved synthetic-scaler words, not real-movie pixels.

    Canonical geometry validation is shared with the independently pinned scorer.
    Only centre-line affine interiors of the scaled six ascending cases enter
    NLQ. The expected samples belong to the declared pixel-centre hypothesis.
    """
    validated = geometry.analyse_report(value)
    repeats = value.get("repeats")
    if type(repeats) is not int or not 2 <= repeats <= 4:
        raise ValueError("declared repeat count must be 2..4")
    _sha(value.get("binary_sha256"))
    _sha(value.get("source_sha256"))
    cases = {}
    for component in ("Y", "Cb", "Cr"):
        for axis in ("x", "y"):
            case = f"{component}-{axis}-ascending"
            source = value["inputs"][case]
            _sha(source.get("sha256"))
            sample = value["results"]["scaled"][case]
            _sha(sample.get("sha256"))
            hashes = sample.get("repeat_sha256")
            if (type(hashes) is not list or len(hashes) != repeats
                    or any(_sha(digest) != sample["sha256"] for digest in hashes)):
                raise ValueError("all repeat hashes must match declared sample hash")
            if type(sample.get("bytes")) is not int or sample["bytes"] != 3840 * 2160 * 8:
                raise ValueError("scaled Y416 byte declaration mismatch")
            if json.dumps(sample.get("UYVA_word_indices_hypothesis"), sort_keys=True) != json.dumps(
                    {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3}, sort_keys=True):
                raise ValueError("canonical UYVA word hypothesis required")
            raw = sample["raw_le16_word_positions"][geometry.WORDS[component]][
                "center_row_raw_words" if axis == "x" else "center_column_raw_words"]
            first, stop = validated["results"]["scaled"][case]["pixel-centre"]["output_index_slice_start_stop"]
            start = source["case_spec"]["band_start_native"]
            sample_errors, residual_errors, final_errors = [], [], []
            distances = {side: [] for side in ("actual", "expected")}
            near = {side: 0 for side in distances}
            zeros = {side: 0 for side in distances}
            clipped = {side: 0 for side in distances}
            actual_fractional = expected_fractional = crossings = neutral_transitions = 0
            examples, near_examples = [], []
            for index in range(first, stop):
                position = geometry.coordinate(index, len(raw), component, axis, "pixel-centre")
                expected = 128 + 8 * (position - start)
                pair = score_pair(raw[index], expected, mapped=32768)
                actual = Fraction(raw[index], 64)
                actual_fractional += actual.denominator != 1
                expected_fractional += expected.denominator != 1
                sample_errors.append(actual - expected)
                residual_errors.append(Fraction(*pair["extension_residual_error_16bit_units"]))
                final_errors.append(pair["synthetic_reconstructed_12bit_actual"] - pair["synthetic_reconstructed_12bit_expected"])
                relations = pair["neutral_relation"]
                crossings += relations["actual"] * relations["expected"] < 0
                neutral_transitions += relations["actual"] != relations["expected"] and 0 in relations.values()
                for side, native in (("actual", actual), ("expected", expected)):
                    distance = native - PARAMETERS["offset"]
                    distances[side].append(distance)
                    near[side] += abs(distance) <= Fraction(1, 2)
                    zeros[side] += distance == 0
                    residual = Fraction(*pair[f"{side}_extension_residual"])
                    unbounded = (32768 + residual + 8) // 16
                    clipped[side] += unbounded != pair[f"synthetic_reconstructed_12bit_{side}"]
                example = dict(output_index=index, **pair)
                if len(examples) < 3:
                    examples.append(example)
                if ((abs(actual - 512) <= Fraction(1, 2) or abs(expected - 512) <= Fraction(1, 2)
                     or relations["actual"] != relations["expected"]) and len(near_examples) < 6):
                    near_examples.append(example)
            count = stop - first
            cases[case] = {
                "samples": count, "component": component, "axis": axis,
                "output_index_slice_start_stop": [first, stop], "margin_output_samples": 32,
                "input_sha256_declared": source["sha256"], "raw_output_sha256_declared": sample["sha256"],
                "sample_error_native_codes_histogram": _histogram(sample_errors),
                "extension_residual_error_16bit_histogram": _histogram(residual_errors),
                "mean_signed_extension_residual_error": rational(sum(residual_errors) / count),
                "mean_absolute_extension_residual_error": rational(sum(map(abs, residual_errors)) / count),
                "maximum_absolute_extension_residual_error": rational(max(map(abs, residual_errors))),
                "actual_fractional_input_count": actual_fractional, "expected_fractional_input_count": expected_fractional,
                "neutral_distance_native_codes": {
                    side: {"minimum_signed": rational(min(values)), "maximum_signed": rational(max(values)),
                           "minimum_absolute": rational(min(map(abs, values))),
                           "within_half_code_inclusive_count": near[side], "exact_neutral_count": zeros[side]}
                    for side, values in distances.items()},
                "opposite_nonzero_sign_count": crossings, "neutral_to_nonzero_transition_count": neutral_transitions,
                "synthetic_mapped_code": 32768, "synthetic_output_bit_depth": 12,
                "synthetic_composition_clipped_counts": clipped,
                "synthetic_reconstructed_12bit_difference_histogram": _histogram(final_errors),
                "first_examples": examples, "near_neutral_or_crossing_examples": near_examples,
            }
    return {
        "geometry_helper_sha256": hashlib.sha256(Path(geometry.__file__).read_bytes()).hexdigest(),
        "input_generator_sha256_declared": value["source_sha256"],
        "binary_sha256_declared": value["binary_sha256"], "declared_repeats": repeats,
        "expected_geometry": "pixel-centre hypothesis; not established Dolby geometry",
        "sample_basis": "actual saved synthetic-scaler raw words versus exact ideal affine-band samples at matching output indices",
        "interpretation": "measured input pairs plus hypothetical fractional NLQ continuation; not movie/RGB, shader or licensed-device prediction",
        "validation_scope": "canonical source declarations/profiles and hash syntax/repeat agreement checked; report bytes hashed by caller, images/binary not re-read",
        "total_samples": sum(case["samples"] for case in cases.values()), "cases": cases,
    }


def report(measured=None):
    cases = []
    # These are synthetic placements of error magnitudes observed against the
    # declared pixel-centre model, NOT replay of measured pixel pairs.
    for component, amplitude in (("Y", Fraction(1, 2)), ("Cb", Fraction(1, 4)), ("Cr", Fraction(1, 4))):
        for anchor in (Fraction(500), Fraction(2047, 4), Fraction(512), Fraction(2049, 4), Fraction(524)):
            for error in (-amplitude, amplitude):
                word = (anchor + error) * 64
                assert word.denominator == 1
                pair = score_pair(int(word), anchor)
                sweep = []
                for mapped in (0, 8, 32768, 65520, 65535):
                    row = {"mapped_code": mapped}
                    for side in ("actual", "expected"):
                        residual = Fraction(*pair[f"{side}_extension_residual"])
                        unbounded = (mapped + residual + 8) // 16
                        reconstructed = reconstruct_extension(mapped, residual)
                        row[side] = {"unbounded_rounded_code": unbounded,
                                     "clipped": reconstructed != unbounded,
                                     "reconstructed_12bit_code": reconstructed}
                    row["signed_reconstructed_code_error"] = (row["actual"]["reconstructed_12bit_code"]
                                                               - row["expected"]["reconstructed_12bit_code"])
                    sweep.append(row)
                cases.append(dict(component=component, synthetic_composition_sweep=sweep, **pair))
    composition_summary = {}
    for component in ("Y", "Cb", "Cr"):
        rows = [row for case in cases if case["component"] == component
                for row in case["synthetic_composition_sweep"]]
        composition_summary[component] = {
            "synthetic_pairs": len(rows),
            "actual_clipped_count": sum(row["actual"]["clipped"] for row in rows),
            "expected_clipped_count": sum(row["expected"]["clipped"] for row in rows),
            "unclipped_pair_count": sum(not row["actual"]["clipped"] and not row["expected"]["clipped"] for row in rows),
            "signed_reconstructed_code_errors": sorted({row["signed_reconstructed_code_error"] for row in rows}),
            "interior_mapped32768_signed_errors": sorted({row["signed_reconstructed_code_error"] for row in rows if row["mapped_code"] == 32768}),
        }
    value = {
        "schema": "yblod.nlq-scaling-sensitivity.v1", "status": "complete",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "integer_reference_sha256": hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest(),
        "specification": {"url": SPEC, "clauses": ["5.4.3.2", "5.4.3.3", "Annex B.3 (informative)"]},
        "parameters": dict(PARAMETERS), "el_bit_depth": 10, "coefficient_log2_denom": 23,
        "parameter_basis": "synthetic fixture matching the verified frame-2296 NLQ coefficient subset; no RPU or pixels included",
        "normative_fractional_behavior": "unknown; integer composer contract does not define this transport extension",
        "model": "exact rational pre-shift standalone algebra with its accumulator bound; final-floor extension reported separately",
        "residual_units": "signed correction units before 16-bit mapped BL plus residual is rounded to 12 bits",
        "integer_contract": "integer-input final-floor results match reference.inverse_el; neither model is a finite-float shader emulator",
        "error_magnitude_basis": "Y +/-1/2 and Cb/Cr +/-1/4 native codes observed in full-size ascending affine bands against the declared pixel-centre hypothesis",
        "error_magnitude_source": "results/intel-y416-large-geometry-v11.json",
        "limitations": ["the default cases use synthetic anchors; optional measured_pairs use actual synthetic-scaler observations, never real-frame predictions",
                        "fractional near-neutral sign reversal/discontinuity is model behavior, not an established Dolby rule",
                        "no shader normalization/noise guard, texture interpolation, RGB, IPT, clipping-frequency or SK4 prediction",
                        "no 10-bit truncation, fitted shift, parameter tuning or production changes"],
        "cases": cases,
        "synthetic_composition_summary": composition_summary,
    }
    if measured is not None:
        data = Path(measured).read_bytes()
        value["measured_pairs"] = analyse_measured(json.loads(data))
        value["measured_pairs"]["input_report_sha256"] = hashlib.sha256(data).hexdigest()
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--measured-report", type=Path)
    args = parser.parse_args()
    value = report(args.measured_report)
    with args.output.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
