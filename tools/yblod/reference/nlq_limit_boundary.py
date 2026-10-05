#!/usr/bin/env python3
"""Exact ideal-source NLQ cap diagnostic, not a GPU or licensed DV model.

The binding maximum is an artificial arithmetic fixture. Local validation is
not evidence of legal bitstream metadata. No production or output-rounding rule
is proposed. See the pinned NLQ_SHADER_AUDIT.md for inspected shader provenance.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import reference

PARAMETERS = {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1024}
CONTROL_MAXIMUM = 1048576
SHADER_SHA256 = "5961adebdc5f4768eb6cf28560f9cb1143c65d3cfbe6be089097347dc232ebcf"


def rational(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def native(sample):
    if type(sample) not in (int, Fraction) or not 0 <= sample <= 1023:
        raise ValueError("sample must be exact int/Fraction in 0..1023")
    return Fraction(sample)


def cap_limit(maximum):
    reference.integer(maximum, "maximum", 0, (2 << 23)-1)
    # Integer reference accumulator limit, divided by its final shift scale.
    return Fraction(2 * maximum, 1 << (23-5-10))


def ideal_shader(sample, *, maximum=None):
    """Ideal source algebra in normalized units; optional hypothetical cap.

    Inspected source has NO metadata cap. Guard is evaluated exactly, not as
    binary32; texture filtering/upload/compiler arithmetic are not simulated.
    """
    sample = native(sample)
    distance = sample - 512
    if abs(distance) <= Fraction(1, 1 << 22) * max(abs(sample), 512):
        value = Fraction(0)
    else:
        direction = 1 if distance > 0 else -1
        value = (distance - Fraction(direction, 2)) / 4096
    if maximum is not None:
        limit = cap_limit(maximum) / 65536
        value = min(limit, max(-limit, value))
    return value


def evaluate(sample, maximum=1024):
    sample = native(sample)
    uncapped = ideal_shader(sample) * 65536
    capped = ideal_shader(sample, maximum=maximum) * 65536
    params = dict(PARAMETERS, maximum=maximum)
    integer = reference.inverse_el(int(sample), params, 10, 23) if sample.denominator == 1 else None
    return {"sample_native_codes": rational(sample),
            "ideal_shader_normalized_uncapped": rational(uncapped/65536),
            "ideal_shader_uncapped_16bit_units": rational(uncapped),
            "hypothetical_capped_16bit_units": rational(capped),
            "cap_difference_16bit_units": rational(capped-uncapped),
            "hypothetical_capped_floor": capped.numerator//capped.denominator,
            "floor_difference_16bit_units": rational(capped.numerator//capped.denominator-capped),
            "unchanged_integer_reference": integer,
            "integer_reference_minus_capped_ideal": None if integer is None else rational(integer-capped)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def histogram(values):
    counts = Counter(values)
    return [{"value": rational(v), "count": counts[v]} for v in sorted(counts)]


def scope(samples, maximum):
    rows = [evaluate(s, maximum) for s in samples]
    caps = [Fraction(*r["cap_difference_16bit_units"]) for r in rows]
    floors = [Fraction(*r["floor_difference_16bit_units"]) for r in rows]
    differences = [Fraction(*r["integer_reference_minus_capped_ideal"]) for r in rows
                   if r["integer_reference_minus_capped_ideal"] is not None]
    return {"samples": len(rows), "evaluated_rows_sha256": digest(rows),
            "sample_coordinates_sha256": digest([rational(s) for s in samples]),
            "cap_changed_samples": sum(bool(v) for v in caps),
            "cap_difference_histogram": histogram(caps),
            "hypothetical_floor_difference_histogram": histogram(floors),
            "integer_comparison_count": len(differences),
            "integer_reference_minus_capped_ideal_histogram": histogram(differences)}


def report():
    here = Path(__file__).resolve().parent
    pins = {name: hashlib.sha256((here/name).read_bytes()).hexdigest()
            for name in (Path(__file__).name, "reference.py", "NLQ_SHADER_AUDIT.md")}
    integers = list(range(1024))
    fractional = [Fraction(w, 64) for w in range((512-3)*64, (512+3)*64+1)]
    selected = [0, 510, 511, Fraction(32767,64), 512, Fraction(32769,64), 513, 514, 1023]
    maxima = {}
    for maximum in (1024, CONTROL_MAXIMUM):
        maxima[str(maximum)] = {"maximum": maximum, "cap_limit_16bit_units": rational(cap_limit(maximum)),
                               "cap_limit_normalized_shader_units": rational(cap_limit(maximum)/65536),
                               "integer_anchors": scope(integers, maximum),
                               "near_neutral_raw_word_sweep": scope(fractional, maximum),
                               "selected_rows": [evaluate(s, maximum) for s in selected]}
    return {"schema": "yblod.nlq-limit-boundary.v1", "status": "complete",
            "parameters_artificial_arithmetic_fixture": PARAMETERS, "bit_depth": 10, "denominator": 23,
            "source_pins_sha256": pins,
            "inspected_external_shader_source": {"path": "src/shaders/colorspace.c",
                                                   "sha256_declared_by_pinned_audit": SHADER_SHA256,
                                                   "re_read_by_this_tool": False},
            "interpretation": ["maximum1024 is artificial arithmetic, not claimed bitstream-legal metadata",
                               "uncapped exact source-defined ideal shader; capped branch is hypothetical",
                               "shader normalized residual multiplied by65536, not65535",
                               "integer reference unchanged; fractional samples have no integer-reference result",
                               "floor diagnostics are hypothetical for fractional inputs, not shader operations",
                               "no final composition,12bit rounding,texture filtering,float upload,GPU or licensed-device emulation",
                               "no policy selection or production changes"],
            "ideal_neutral_guard_native_width": {"below": rational(Fraction(1,8192)),
                                                  "above": rational(Fraction(512,(1<<22)-1))},
            "binding_fixture_cap_transition_absolute_distance_native": rational(1),
            "secondary_clamp_before_floor_control": {
                "maximum": 1025, "cap_limit_16bit_units": rational(cap_limit(1025)),
                "selected_rows": [evaluate(510,1025), evaluate(514,1025)],
                "interpretation": "clip signed accumulator before floor: positive8, negative-9; not symmetric cap of already-floored residual"},
            "fixtures": maxima}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("new_json")
    args = parser.parse_args()
    value = report()
    with Path(args.new_json).open("x") as target:
        json.dump(value, target, indent=2, sort_keys=True)
        target.write("\n")


if __name__ == "__main__":
    main()
