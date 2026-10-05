"""Full-size centre-line affine diagnostics, not fitted/Dolby geometry.

LEFT420 chroma source centres are (2*i,2*j+1/2) in source-luma indices.
All raw word bits are retained. Score only a declared affine-band interior.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path

MODELS = ("co-sited", "pixel-centre", "annex-b-mixed")
INPUT = [1920, 1080]
COMPONENT_SIZES = {"Y": INPUT, "Cb": [960, 540], "Cr": [960, 540]}
WORDS = {"Cb": "0", "Y": "1", "Cr": "2"}


def rational(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def coordinate(index, output_length, component, axis, model):
    if (type(index) is not int or type(output_length) is not int
            or component not in WORDS or axis not in ("x", "y") or model not in MODELS):
        raise ValueError("invalid coordinate declaration")
    native_length = INPUT[0 if axis == "x" else 1]
    if output_length not in (native_length, native_length * 2) or not 0 <= index < output_length:
        raise ValueError("native or2x luma raster required")
    scale = Fraction(native_length, output_length)
    position = index * scale
    if model == "pixel-centre" or (model == "annex-b-mixed" and axis == "y"):
        position = (index + Fraction(1, 2)) * scale - Fraction(1, 2)
    if component != "Y":
        position = (position - (Fraction(1, 2) if axis == "y" else 0)) / 2
    return position


def score_profile(raw, component, axis):
    if (component not in WORDS or axis not in ("x", "y") or not isinstance(raw, list)
            or any(type(v) is not int or not 0 <= v <= 65535 for v in raw)):
        raise ValueError("unmodified raw16 integer profile required")
    native_length = COMPONENT_SIZES[component][0 if axis == "x" else 1]
    start = native_length // 2 - 48
    factor = Fraction(len(raw), native_length)
    first, stop = int(start * factor) + 32, int((start + 96) * factor) - 32
    if first >= stop or factor.denominator != 1:
        raise ValueError("invalid band expansion")
    results = {}
    for model in MODELS:
        parity = {str(p): [] for p in range(4)}
        for index in range(first, stop):
            position = coordinate(index, len(raw), component, axis, model)
            if not start < position < start + 95:
                raise ValueError("score touches non-affine source boundary")
            expected = 128 + 8 * (position - start)
            parity[str(index % 4)].append(Fraction(raw[index], 64) - expected)
        errors = [v for values in parity.values() for v in values]
        results[model] = {
            "output_index_slice_start_stop": [first, stop], "samples": len(errors),
            "margin_output_samples": 32,
            "signed_native_code_error_values": [rational(v) for v in sorted(set(errors))],
            "axis_mod4_signed_native_code_error_values": {
                p: [rational(v) for v in sorted(set(values))] for p, values in parity.items()},
            "mean_signed_native_code_error": rational(sum(errors) / len(errors)),
            "maximum_absolute_native_code_error": rational(max(abs(v) for v in errors)),
        }
    return results


def analyse_report(report):
    if (not isinstance(report, dict) or report.get("schema") != "yblod.hardware-y416-large.v1"
            or report.get("status") != "complete" or report.get("all_sameformat_p010_gates_complete") is not True):
        raise ValueError("complete gated large-format report required")
    results = {"schema": "yblod.y416-large-geometry.v1", "status": "complete", "results": {},
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "interpretation": "centre-line affine-band observations against predeclared hypotheses; not whole-frame acceptance or licensed-Dolby geometry; image hashes not recomputed"}
    for label, size in (("native", INPUT), ("scaled", [3840, 2160])):
        scored = results["results"][label] = {}
        for component in WORDS:
            for axis in ("x", "y"):
                case = f"{component}-{axis}-ascending"
                spec = report["inputs"][case]["case_spec"]
                extent = COMPONENT_SIZES[component][0 if axis == "x" else 1]
                start = extent // 2 - 48
                required = {"component": component, "axis": axis, "signed_slope": 8,
                            "baseline_code": 512, "native_band_length": 96,
                            "band_start_native": start, "band_stop_native_exclusive": start + 96,
                            "source_center_native_index": start + 48,
                            "band_first_code": 128, "band_last_code": 888,
                            "native_component_sizes": COMPONENT_SIZES, "input_size": INPUT}
                # Strict JSON structural types: floats and booleans are not native integer metadata.
                if json.dumps(spec, sort_keys=True) != json.dumps(required, sort_keys=True):
                    raise ValueError("canonical source band declarations required")
                sample = report["results"][label][case]
                if (sample["size"] != size or not isinstance(sample["size"], list)
                        or any(type(v) is not int for v in sample["size"])
                        or sample["repeat_stable"] is not True
                        or json.dumps(sample["profile_sampling"], sort_keys=True) != json.dumps(
                            {"center_row_y": size[1] // 2, "center_column_x": size[0] // 2}, sort_keys=True)):
                    raise ValueError("canonical stable centre-line sample required")
                raw = sample["raw_le16_word_positions"][WORDS[component]][
                    "center_row_raw_words" if axis == "x" else "center_column_raw_words"]
                if len(raw) != size[0 if axis == "x" else 1]:
                    raise ValueError("full-raster profile length mismatch")
                scored[case] = score_profile(raw, component, axis)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = args.report.read_bytes()
    result = analyse_report(json.loads(data))
    result["input_report_sha256"] = hashlib.sha256(data).hexdigest()
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
