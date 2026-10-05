"""Exact descriptive edge/stripe metrics, NOT filter or Dolby conformance.

The declared stimulus is a +64-code step/stripe over neutral code 512.
All sixteen output bits are retained. Native-equivalent codes mean raw/64,
not an integer shift. Fractions are JSON objects with numerator/denominator.
Threshold interpolation describes a measured segment; it fits no filter.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re


AMPLITUDE_RAW = 4096
MARGIN = 16
COMPONENT_WORD = {"Cb": "0", "Y": "1", "Cr": "2"}
SIZES = {"Y": [64, 64], "Cb": [32, 32], "Cr": [32, 32]}


def rational(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _profile(value):
    if (not isinstance(value, list) or len(value) not in (64, 128)
            or any(type(word) is not int or not 0 <= word <= 65535 for word in value)):
        raise ValueError("64/128 unmodified unsigned16 integer words required")
    return value


def _common(rawprofile, baselineprofile):
    raw = _profile(rawprofile)
    baseline = _profile(baselineprofile)
    if len(raw) != len(baseline):
        raise ValueError("profile and baseline geometry differ")
    differences = [a - b for a, b in zip(raw, baseline)]
    result = {
        "profile_length": len(raw),
        "raw_words": list(raw), "baseline_raw_words": list(baseline),
        "raw_differences": differences,
        "native_code_differences": [rational(Fraction(d, 64)) for d in differences],
        "raw_endpoint_counts": {
            "actual_zero": raw.count(0), "actual_65535": raw.count(65535),
            "baseline_zero": baseline.count(0), "baseline_65535": baseline.count(65535),
        },
        "baseline_minus_declared_512_native_codes": {
            "mean": rational(Fraction(sum(b - 32768 for b in baseline), 64 * len(baseline))),
            "maximum_absolute": rational(Fraction(max(abs(b - 32768) for b in baseline), 64)),
        },
        "phase_groups": {},
        "interpretation": "descriptive raw response; no fitted phase, area normalization or conformance verdict",
    }
    for period in (2, 4):
        result["phase_groups"][str(period)] = {
            str(p): {
                "samples": len(differences[p::period]),
                "sum_signed_raw_difference": sum(differences[p::period]),
                "sum_absolute_raw_difference": sum(abs(d) for d in differences[p::period]),
            } for p in range(period)
        }
    return result, differences


def _crossings(values, threshold):
    """Return every crossing/touch, including ambiguous threshold plateaus."""
    events = []
    n = len(values)
    for index in range(n - 1):
        a, b = values[index:index + 2]
        if (a < threshold < b) or (a > threshold > b):
            position = index + Fraction(threshold - a, b - a)
            events.append({
                "direction": "rising" if a < b else "falling",
                "sample_bracket": [index, index + 1],
                "position_samples": rational(position),
                "position_interval_samples": [rational(position), rational(position)],
            })
    index = 0
    while index < n:
        if values[index] != threshold:
            index += 1
            continue
        first = index
        while index + 1 < n and values[index + 1] == threshold:
            index += 1
        last = index
        if first == 0 or last == n - 1:
            direction = "boundary"
        elif values[first - 1] < threshold < values[last + 1]:
            direction = "rising"
        elif values[first - 1] > threshold > values[last + 1]:
            direction = "falling"
        else:
            direction = "touch"
        events.append({
            "direction": direction, "sample_bracket": [first, last],
            "position_samples": rational(first) if first == last else None,
            "position_interval_samples": [rational(first), rational(last)],
        })
        index += 1
    return sorted(events, key=lambda event: event["sample_bracket"])


def _as_fraction(value):
    return Fraction(value["numerator"], value["denominator"])


def score_step(rawprofile, baselineprofile):
    result, differences = _common(rawprofile, baselineprofile)
    n = len(differences)
    # For 64 samples, [16:32] would touch the edge. Keep an additional gap.
    width = min(16, (n - 2 * MARGIN) // 4)
    windows = {"before": (MARGIN, MARGIN + width, 0),
               "after": (n - MARGIN - width, n - MARGIN, AMPLITUDE_RAW)}
    result.update(metric_kind="step", stimulus_amplitude_raw=AMPLITUDE_RAW,
                  stimulus_amplitude_native_codes=64, plateau_check_windows={},
                  margin_output_samples=MARGIN)
    for name, (start, stop, expected) in windows.items():
        errors = [d - expected for d in differences[start:stop]]
        result["plateau_check_windows"][name] = {
            "slice_start_stop": [start, stop], "samples": len(errors),
            "expected_raw_difference": expected,
            "mean_signed_native_code_error": rational(Fraction(sum(errors), 64 * len(errors))),
            "maximum_absolute_native_code_error": rational(Fraction(max(map(abs, errors)), 64)),
            "interpretation": "fixed interior check band, not an assertion that the response has settled",
        }
    interior = differences[MARGIN:n - MARGIN]
    result["interior_overshoot_native_codes"] = rational(Fraction(max(0, max(interior) - AMPLITUDE_RAW), 64))
    result["interior_undershoot_native_codes"] = rational(Fraction(max(0, -min(interior)), 64))
    result["crossings"] = {}
    positions = []
    for percentage in (10, 50, 90):
        threshold = Fraction(AMPLITUDE_RAW * percentage, 100)
        events = _crossings(differences, threshold)
        result["crossings"][str(percentage)] = {
            "threshold_raw_difference": rational(threshold), "events": events,
        }
        if (len(events) == 1 and events[0]["direction"] == "rising"
                and events[0]["position_samples"] is not None):
            positions.append(_as_fraction(events[0]["position_samples"]))
    valid = (len(positions) == 3 and positions == sorted(positions)
             and all(MARGIN <= p <= n - MARGIN - 1 for p in positions))
    result["unique_interior_rising_crossings"] = valid
    result["width_10_to_90_output_samples"] = rational(positions[2] - positions[0]) if valid else None
    result["crossing_measurement"] = "exact straight-segment interpolation between observed samples; threshold plateaus retain intervals"
    return result


def score_impulse(rawprofile, baselineprofile):
    result, differences = _common(rawprofile, baselineprofile)
    mass = sum(differences)
    absolute = sum(map(abs, differences))
    moment = sum(index * value for index, value in enumerate(differences))

    def support(threshold):
        indices = [i for i, value in enumerate(differences) if abs(value) > threshold]
        return [indices[0], indices[-1]] if indices else None

    result.update({
        "metric_kind": "impulse_stripe", "stimulus_amplitude_raw": AMPLITUDE_RAW,
        "signed_mass_raw": mass, "absolute_mass_raw": absolute,
        "positive_lobe_mass_raw": sum(max(d, 0) for d in differences),
        "negative_lobe_magnitude_raw": sum(max(-d, 0) for d in differences),
        "signed_mass_native_codes": rational(Fraction(mass, 64)),
        "absolute_mass_native_codes": rational(Fraction(absolute, 64)),
        "first_moment_raw_times_output_sample": moment,
        "centroid_output_samples": rational(Fraction(moment, mass)) if mass > 0 else None,
        "centroid_unavailable_reason": None if mass > 0 else "non-positive signed mass",
        "cancellation_ratio": rational(Fraction(absolute, abs(mass))) if mass else None,
        "minimum_native_code_difference": rational(Fraction(min(differences), 64)),
        "maximum_native_code_difference": rational(Fraction(max(differences), 64)),
        "exact_nonzero_support_inclusive": support(0),
        "greater_than_one_native_code_support_inclusive": support(64),
        "nonzero_at_profile_boundary": bool(differences[0] or differences[-1]),
        "interpretation": "observed finite-profile signed moments; no unit-area normalization or presumed correct centroid; constant preservation does not establish phase-wise impulse mass",
    })
    return result


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _expected_spec(component=None, axis=None, kind="neutral"):
    return {"component": component, "axis": axis, "kind": kind,
            "baseline_code": 512, "increment_code": 64,
            "change_native_index": None if component is None else (32 if component == "Y" else 16),
            "native_component_sizes": SIZES, "input_size": [64, 64]}


def _exact(actual, expected):
    """Structural equality that does not accept booleans as integers."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_exact(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_exact(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _sample(sample, size):
    if not isinstance(sample, dict):
        raise ValueError("sample object required")
    repeats = sample.get("repeat_sha256")
    if (not _exact(sample.get("size"), [size, size])
            or type(sample.get("bytes")) is not int or sample["bytes"] != size * size * 8
            or sample.get("repeat_stable") is not True or not _hash(sample.get("sha256"))
            or not isinstance(repeats, list) or not 2 <= len(repeats) <= 4
            or any(not _hash(value) or value != sample["sha256"] for value in repeats)
            or not _exact(sample.get("profile_sampling"), {"center_row_y": size // 2, "center_column_x": size // 2})
            or not _exact(sample.get("UYVA_word_indices_hypothesis"), {"Cb": 0, "Y": 1, "Cr": 2, "alpha": 3})):
        raise ValueError("stable canonical geometry, profile coordinates and word mapping required")
    words = sample.get("raw_le16_word_positions")
    if not isinstance(words, dict) or set(words) != {"0", "1", "2", "3"}:
        raise ValueError("all four raw word positions required")
    for word in words.values():
        for key in ("center_row_raw_words", "center_column_raw_words"):
            if not isinstance(word, dict) or len(_profile(word.get(key))) != size:
                raise ValueError("raw profile size mismatch")
    return words


def analyse_report(report):
    """Validate aggregate declarations and score saved profiles; read no images."""
    if (not isinstance(report, dict) or report.get("schema") != "yblod.hardware-y416-edges.v1"
            or report.get("status") != "complete"
            or report.get("all_sameformat_p010_gates_complete") is not True):
        raise ValueError("complete Y416 edges report required")
    specs = {"neutral": _expected_spec()}
    for component in ("Y", "Cb", "Cr"):
        for axis in ("x", "y"):
            for kind in ("step", "impulse"):
                specs[f"{component}-{axis}-{kind}"] = _expected_spec(component, axis, kind)
    inputs, results = report.get("inputs"), report.get("results")
    if (not isinstance(inputs, dict) or set(inputs) != set(specs)
            or not isinstance(results, dict) or set(results) != {"64", "128"}):
        raise ValueError("complete canonical 13-case, two-size corpus required")
    for case, spec in specs.items():
        item = inputs[case]
        if (not isinstance(item, dict) or not _hash(item.get("sha256"))
                or not _exact(item.get("case_spec"), spec)):
            raise ValueError("canonical single-component stimulus declarations required")
    output = {
        "schema": "yblod.y416-edge-metrics.v1", "status": "complete",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fraction_encoding": {"numerator": "integer", "denominator": "positive integer"},
        "interpretation": "saved center-line measurements, not whole-frame acceptance, identified kernel, correction or Dolby conformance",
        "validation_scope": "report declarations/profile values checked; declared image hashes are not recomputed and pixels are not read",
        "input_hashes": {case: item["sha256"] for case, item in inputs.items()},
        "results": {},
    }
    for size in (64, 128):
        cases = results[str(size)]
        if not isinstance(cases, dict) or set(cases) != set(specs):
            raise ValueError("missing or unexpected case")
        neutral = _sample(cases["neutral"], size)
        scored = output["results"][str(size)] = {}
        for case, spec in specs.items():
            if case == "neutral":
                continue
            sample = cases[case]
            words = _sample(sample, size)
            component, axis, kind = spec["component"], spec["axis"], spec["kind"]
            key = "center_row_raw_words" if axis == "x" else "center_column_raw_words"
            index = COMPONENT_WORD[component]
            method = score_step if kind == "step" else score_impulse
            scored[case] = method(words[index][key], neutral[index][key])
            scored[case].update({
                "case_spec": spec, "observed_sha256": sample["sha256"],
                "neutral_sha256": cases["neutral"]["sha256"],
                "stimulus_raw_word_position": int(index), "profile_axis": axis,
                "nominal_output_samples_per_native_component_sample": size // (64 if component == "Y" else 32),
                "collateral_center_profile_changes": {
                    name: {
                        "different_words": sum(a != b for a, b in zip(words[word][key], neutral[word][key])),
                        "maximum_absolute_raw_difference": max(abs(a - b) for a, b in zip(words[word][key], neutral[word][key])),
                    } for name, word in {"Y": "1", "Cb": "0", "Cr": "2", "alpha": "3"}.items()
                    if word != index
                },
            })
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    data = args.report.read_bytes()
    result = analyse_report(json.loads(data))
    result["input_report_sha256"] = hashlib.sha256(data).hexdigest()
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
