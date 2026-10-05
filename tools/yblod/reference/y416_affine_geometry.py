"""Exact affine profile comparisons against DECLARED coordinate hypotheses.

No learned phase, rounding, bit masking, or claimed Dolby reference geometry.
Input LEFT 420 chroma sits at source-luma (2*i, 2*j+1/2); output 444
components are compared at common output-luma sample positions.
"""
from fractions import Fraction
import argparse
import hashlib
import json
from pathlib import Path

MODELS = ("co-sited", "pixel-centre", "annex-b-mixed")


def coordinate(index, output_size, component, axis, model):
    if (type(index) is not int or type(output_size) is not int
            or output_size not in (64, 128) or not 0 <= index < output_size
            or component not in ("Y", "Cb", "Cr") or axis not in ("x", "y")
            or model not in MODELS):
        raise ValueError("invalid declared geometry")
    ratio = Fraction(64, output_size)
    source = index * ratio
    if model == "pixel-centre" or (model == "annex-b-mixed" and axis == "y"):
        source = (index + Fraction(1, 2)) * ratio - Fraction(1, 2)
    if component != "Y":
        source = (source - (Fraction(1, 2) if axis == "y" else 0)) / 2
    return source


def rational(value):
    return [value.numerator, value.denominator]


def score_profile(raw_words, *, component, axis, base, slope, margin=16):
    if (not isinstance(raw_words, list) or len(raw_words) not in (64, 128)
            or any(type(w) is not int or not 0 <= w <= 65535 for w in raw_words)
            or type(base) is not int or type(slope) is not int or slope not in (-8, 8)
            or type(margin) is not int or margin < 1 or margin * 2 >= len(raw_words)):
        raise ValueError("bounded raw16 affine profile required")
    result = {}
    size = len(raw_words)
    for model in MODELS:
        errors = {str(p): [] for p in range(4)}
        for index in range(margin, size - margin):
            expected_code = base + slope * coordinate(index, size, component, axis, model)
            errors[str(index % 4)].append(Fraction(raw_words[index], 64) - expected_code)
        all_errors = [e for values in errors.values() for e in values]
        result[model] = {
            "interior_samples": len(all_errors), "margin_output_samples": margin,
            "signed_native_code_error_values": [rational(e) for e in sorted(set(all_errors))],
            "axis_mod4_signed_native_code_error_values": {
                p: [rational(e) for e in sorted(set(values))] for p, values in errors.items()},
            "mean_signed_native_code_error": rational(sum(all_errors) / len(all_errors)),
            "maximum_absolute_native_code_error": rational(max(abs(e) for e in all_errors)),
            "interpretation": "exact hypothesis comparison, NOT acceptance or fitted correction",
        }
    return result


def analyse_report(report):
    if (report.get("schema") != "yblod.hardware-y416-spatial.v1"
            or report.get("status") != "complete"):
        raise ValueError("complete spatial report required")
    output = {"schema": "yblod.y416-affine-geometry.v1", "status": "complete", "results": {},
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "interpretation": "centre-line observations versus predeclared coordinate hypotheses; not whole-frame acceptance or Dolby conformance"}
    for size in (64, 128):
        cases = report["results"][str(size)]
        scored = output["results"][str(size)] = {}
        for component in ("Y", "Cb", "Cr"):
            for axis in ("x", "y"):
                for direction, slope in (("ascending", 8), ("descending", -8)):
                    case = f"{component}-{axis}-{direction}"
                    sample = cases[case]
                    spec = report["inputs"][case]["case_spec"]
                    source_size = 64 if component == "Y" else 32
                    base = 512 - slope * (source_size // 2)
                    bases = {c: base if c == component else 512 for c in ("Y", "Cb", "Cr")}
                    if (spec["component"] != component or spec["axis"] != axis
                            or type(spec["signed_slope"]) is not int or spec["signed_slope"] != slope
                            or spec["base_codes_at_origin"] != bases
                            or any(type(v) is not int for v in spec["base_codes_at_origin"].values())
                            or sample["size"] != [size, size]
                            or not isinstance(sample["size"], list)
                            or any(type(v) is not int for v in sample["size"])
                            or sample["repeat_stable"] is not True):
                        raise ValueError("canonical isolated affine case required")
                    index = {"Cb": "0", "Y": "1", "Cr": "2"}[component]
                    raw = sample["raw_le16_word_positions"][index]
                    profile = raw["center_row_raw_words" if axis == "x" else "center_column_raw_words"]
                    if len(profile) != size:
                        raise ValueError("profile geometry mismatch")
                    scored[case] = score_profile(profile, component=component, axis=axis, base=base, slope=slope)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = args.report.read_bytes()
    result = analyse_report(json.loads(data))
    result["spatial_report_sha256"] = hashlib.sha256(data).hexdigest()
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
