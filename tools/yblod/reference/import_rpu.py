#!/usr/bin/env python3
"""Translate dovi_tool 2.3.4 JSON into exact integer composition instructions.

This produces metadata only. It does not resample native layers, resolve chroma
siting, or claim the resulting extraction is ready for reference.py.
"""
import argparse
import json
from pathlib import Path

from extract_frame import digest, save_json
from reference import SCHEMA, integer, validate


def sized(values, count, name):
    if not isinstance(values, list) or len(values) != count:
        raise ValueError(f"{name}: expected {count} values")
    return values


def fixed(whole, fraction, denominator):
    integer(whole, "coefficient integer part", -65536, 65535)
    integer(fraction, "coefficient fractional part", 0, (1 << denominator) - 1)
    return (whole << denominator) + fraction


def combine(whole, fraction, denominator, count):
    return [fixed(a, b, denominator) for a, b in zip(
        sized(whole, count, "integer coefficients"), sized(fraction, count, "fractional coefficients"))]


def normalize(rpu, identity):
    header = rpu["header"]
    if rpu["dovi_profile"] != 7 or rpu["el_type"] != "FEL":
        raise ValueError("this importer currently supports Profile 7 FEL only")
    if header["use_prev_vdr_rpu_flag"]:
        raise ValueError("previous-RPU state must be resolved explicitly; unsupported here")
    for key, expected in (("coefficient_data_type", 0), ("rpu_type", 2), ("rpu_format", 18),
                          ("vdr_rpu_normalized_idc", 1), ("ext_mapping_idc_0_4", 0),
                          ("ext_mapping_idc_5_7", 0)):
        if header[key] != expected:
            raise ValueError(f"unsupported {key}")
    denominator = integer(header["coefficient_log2_denom"], "coefficient_log2_denom", 13, 32)
    if header["coefficient_log2_denom_length"] != denominator:
        raise ValueError("coefficient denominator and field length differ")
    mapping = rpu["rpu_data_mapping"]
    for key in ("mapping_color_space", "mapping_chroma_format_idc", "num_x_partitions_minus1", "num_y_partitions_minus1"):
        if mapping[key] != 0:
            raise ValueError(f"unsupported {key}")
    result = dict(identity, bl_bit_depth=header["bl_bit_depth_minus8"] + 8,
                  el_bit_depth=header["el_bit_depth_minus8"] + 8,
                  output_bit_depth=header["vdr_bit_depth_minus8"] + 8,
                  coefficient_log2_denom=denominator, disable_residual=header["disable_residual_flag"],
                  mappings=[])
    for curve in sized(mapping["curves"], 3, "curves"):
        count = integer(curve["num_pivots_minus2"], "num_pivots_minus2", 0, 15) + 2
        pivots, total = [], 0
        for delta in sized(curve["pivots"], count, "pivot deltas"):
            total += integer(delta, "pivot delta", 0, (1 << result["bl_bit_depth"]) - 1)
            pivots.append(total)
        pieces = count - 1
        segments = []
        if curve["mapping_idc"] == "Polynomial" and "mmr_coef" not in curve:
            for key in ("poly_order_minus1", "linear_interp_flag", "poly_coef_int", "poly_coef"):
                sized(curve[key], pieces, key)
            for i in range(pieces):
                if curve["linear_interp_flag"][i]:
                    raise ValueError("polynomial interpolation is unsupported")
                order = integer(curve["poly_order_minus1"][i], "poly_order_minus1", 0, 1) + 1
                segments.append({"method": "polynomial", "coefficients": combine(
                    curve["poly_coef_int"][i], curve["poly_coef"][i], denominator, order + 1)})
        elif curve["mapping_idc"] == "MMR" and "poly_coef" not in curve:
            for key in ("mmr_order_minus1", "mmr_constant_int", "mmr_constant", "mmr_coef_int", "mmr_coef"):
                sized(curve[key], pieces, key)
            for i in range(pieces):
                order = integer(curve["mmr_order_minus1"][i], "mmr_order_minus1", 0, 2) + 1
                whole = sized(curve["mmr_coef_int"][i], order, "MMR integer rows")
                fraction = sized(curve["mmr_coef"][i], order, "MMR fractional rows")
                segments.append({"method": "mmr", "constant": fixed(
                    curve["mmr_constant_int"][i], curve["mmr_constant"][i], denominator),
                    "coefficients": [combine(a, b, denominator, 7) for a, b in zip(whole, fraction)]})
        else:
            raise ValueError("unsupported or mixed component mapping")
        result["mappings"].append({"pivots": pivots, "segments": segments})
    if not result["disable_residual"]:
        if mapping["nlq_method_idc"] != "LinearDeadzone" or mapping["nlq_num_pivots_minus2"] != 0:
            raise ValueError("only single-piece linear-deadzone NLQ is supported")
        if mapping["nlq_pred_pivot_value"] != [0, (1 << result["el_bit_depth"]) - 1]:
            raise ValueError("unsupported NLQ pivot range")
        nlq = mapping["nlq"]
        offsets = sized(nlq["nlq_offset"], 3, "NLQ offsets")
        parameters = {}
        for output, source in (("slope", "linear_deadzone_slope"),
                               ("threshold", "linear_deadzone_threshold"), ("maximum", "vdr_in_max")):
            parameters[output] = combine(nlq[source + "_int"], nlq[source], denominator, 3)
        result["nlq_method"] = "linear_deadzone"
        result["nlq"] = [dict(offset=offsets[i], **{key: value[i] for key, value in parameters.items()})
                         for i in range(3)]
    # Validate only the metadata contract, using an internal placeholder envelope.
    # This does not validate or relabel the native picture planes/chroma location.
    validate({"schema": SCHEMA, "width": 2, "height": 2, "format": "yuv420p-u16le-lsb",
              "transfer": "pq", "chroma_location": "left", "preparation": "metadata validation only",
              "bl": identity, "el": identity, "metadata": result})
    return result


def import_bundle(directory):
    directory = Path(directory)
    extraction = json.loads((directory / "extraction.json").read_text())
    if extraction["schema"] != "yblod.extracted-frame.v1" or extraction["status"] != "complete":
        raise ValueError("a completed extraction is required")
    if not extraction["rpu_matches_source_packet_and_global_index"]:
        raise ValueError("RPU/source packet match was not verified")
    if digest(directory / "frame.rpu.bin") != extraction["rpu_sha256"]:
        raise ValueError("RPU changed after extraction")
    rpu = json.loads((directory / "rpu.json").read_text())
    if digest(directory / "rpu.json") != extraction["rpu_json_sha256"]:
        raise ValueError("parsed RPU changed after extraction")
    identity = {"frame_id": f"{extraction['source_sha256']}:{extraction['source_packet_index_zero_based']}",
                "pts": extraction["pts"], "time_base": extraction["time_base"]}
    normalized = {"schema": "yblod.composition-instructions.v1", "metadata": normalize(rpu, identity),
                  "source_extraction_sha256": digest(directory / "extraction.json"),
                  "source_rpu_json_sha256": digest(directory / "rpu.json"),
                  "source_header": rpu["header"], "importer_sha256": digest(__file__),
                  "scope": "Metadata only. Native layer alignment/scaling and MMR luma preparation are pending."}
    save_json(directory / "composition.json", normalized)
    return normalized


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        import_bundle(args.directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"RPU import: {error}\n")
    print(args.directory / "composition.json")
