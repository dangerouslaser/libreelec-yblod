"""Bind supported source colour instructions to a saved extraction and composer.

This verifies the saved association chain, not source-film bytes, decoded image
content, licensed output, or authenticity of a self-consistent forged bundle.
No RPU or picture files are written by load(). Configuration targets and output
policy remain explicit caller choices, separate from verified source metadata.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

import colour_stage
import import_rpu
import reference

LIMIT = 8 << 20
ASSOCIATION = "verified-extracted-rpu"
IDENTITY_MATRIX = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def _snapshot(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _read(root, filename):
    root = Path(root).resolve()
    if type(filename) is not str or not filename or Path(filename).is_absolute():
        raise ValueError("nonempty relative metadata filename required")
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("metadata path escapes bundle")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    try:
        initial = os.fstat(descriptor)
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > LIMIT:
            raise ValueError("metadata must be a regular file of at most8MiB")
        handle = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        raw = handle.read(LIMIT + 1)
        if len(raw) > LIMIT or len(raw) != initial.st_size or _snapshot(os.fstat(handle.fileno())) != _snapshot(initial):
            raise ValueError("metadata changed or exceeded size bound while reading")
        if _snapshot(path.stat()) != _snapshot(initial):
            raise ValueError("metadata path changed while reading")
    return raw, hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON keys are unsupported")
        result[key] = value
    return result


def _json(root, filename):
    raw, digest = _read(root, filename)
    def nonfinite(value):
        raise ValueError(f"non-finite JSON constant {value}")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=nonfinite)
    if type(value) is not dict:
        raise ValueError("metadata JSON object required")
    return value, digest


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("lowercase SHA256 declaration required")
    return value


def _same(first, second):
    return json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)


def _active(dm, width, height):
    block = dm.get("cmv29_metadata")
    if type(block) is not dict or type(block.get("ext_metadata_blocks")) is not list:
        raise ValueError("CMv2.9 active-area metadata required")
    blocks = block["ext_metadata_blocks"]
    if type(block.get("num_ext_blocks")) is not int or block["num_ext_blocks"] != len(blocks):
        raise ValueError("extension block count mismatch")
    if any(type(value) is not dict for value in blocks):
        raise ValueError("extension blocks must be objects")
    areas = [value["Level5"] for value in blocks if "Level5" in value]
    if len(areas) != 1 or type(areas[0]) is not dict:
        raise ValueError("exactly one Level5 active area required")
    area = areas[0]
    margins = [reference.integer(area[f"active_area_{side}_offset"], f"active {side}", 0, 8192)
               for side in ("left", "top", "right", "bottom")]
    left, top, right_margin, bottom_margin = margins
    right, bottom = width - right_margin, height - bottom_margin
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height or left % 2 or right % 2:
        raise ValueError("invalid active rectangle or unpaired horizontal boundary")
    return [left, top, right, bottom]


def load(result, extraction):
    """Read only bounded metadata; colour_frame separately validates stage pixels."""
    result, extraction = Path(result).resolve(), Path(extraction).resolve()
    composer, composer_hash = _json(result, "report.json")
    if composer.get("schema") != "yblod.composer-result.v1" or composer.get("status") != "complete":
        raise ValueError("completed composer report required")
    manifest = composer["input_manifest"]
    reference.validate(manifest)
    if manifest["metadata"]["output_bit_depth"] != 12:
        raise ValueError("12-bit prepared PQ 420-left composition required")
    extracted, extraction_hash = _json(extraction, "extraction.json")
    if (extracted.get("schema") != "yblod.extracted-frame.v1" or extracted.get("status") != "complete"
            or extracted.get("rpu_matches_source_packet_and_global_index") is not True):
        raise ValueError("complete extraction with verified source-packet/RPU association required")
    details = manifest["preparation_details"]
    if _sha(details["source_extraction_sha256"]) != extraction_hash:
        raise ValueError("preparation/extraction hash mismatch")
    source_hash = _sha(extracted["source_sha256"])
    index = reference.integer(extracted["source_packet_index_zero_based"], "source packet index", 0, (1 << 63) - 1)
    identity = {"frame_id": f"{source_hash}:{index}", "pts": extracted["pts"], "time_base": extracted["time_base"]}
    reference.frame_identity(identity)
    if not _same(identity, {key: manifest["metadata"][key] for key in identity}):
        raise ValueError("extraction/composition frame identity mismatch")
    layer = extracted["layers"]["bl"]
    if (type(layer["width"]) is not int or type(layer["height"]) is not int
            or [layer["width"], layer["height"]] != [manifest["width"], manifest["height"]]):
        raise ValueError("extracted BL/composer geometry mismatch")
    rpu, rpu_json_hash = _json(extraction, "rpu.json")
    if _sha(extracted["rpu_json_sha256"]) != rpu_json_hash:
        raise ValueError("parsed RPU hash mismatch")
    binary, rpu_binary_hash = _read(extraction, "frame.rpu.bin")
    if not binary or _sha(extracted["rpu_sha256"]) != rpu_binary_hash:
        raise ValueError("raw RPU hash mismatch")
    normalized = import_rpu.normalize(rpu, identity)
    if not _same(normalized, manifest["metadata"]):
        raise ValueError("normalized RPU/composer metadata mismatch")
    dm = rpu["vdr_dm_data"]
    # Validate the supported source-DM subset with inert diagnostic targets;
    # this makes no actual target or rendering-policy selection.
    colour_stage.ColourConfig.from_dm(dm, target_ycc=IDENTITY_MATRIX, target_lms=IDENTITY_MATRIX,
        target_offset=(0, 0, 0), pq_policy="reject-outside-unit", code_scale=4096)
    rectangle = _active(dm, manifest["width"], manifest["height"])
    provenance = {
        "schema": "yblod.colour-metadata-provenance.v1", "association": ASSOCIATION,
        "composer_report_sha256": composer_hash, "source_extraction_sha256": extraction_hash,
        "rpu_json_sha256": rpu_json_hash, "rpu_binary_sha256": rpu_binary_hash,
        "source_sha256_declared": source_hash, "source_packet_index_zero_based": index,
        "normalization_exact": True,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_sha256": {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                          for module in (import_rpu, reference, colour_stage)},
        "scope": "saved extraction/preparation association checked; source film/packet and stage pixels not re-read; not authenticity or licensed conformance",
        "input_change_check": "per-file descriptor/path metadata during bounded reads, not a simultaneous immutable snapshot",
    }
    return {"source_dm": dm, "identity": identity, "active_rectangle": rectangle,
            "composer_report_sha256": composer_hash, "provenance": provenance}


def make_configuration(result, extraction, destination, *, target_ycc, target_lms,
                       target_offset, pq_policy, outside_codes, code_scale):
    verified = load(result, extraction)
    colour_stage.ColourConfig.from_dm(verified["source_dm"], target_ycc=target_ycc,
        target_lms=target_lms, target_offset=target_offset, pq_policy=pq_policy, code_scale=code_scale)
    if (type(outside_codes) not in (list, tuple) or len(outside_codes) != 3
            or any(type(value) is not int or not 0 <= value <= 4095 for value in outside_codes)):
        raise ValueError("three explicit outside-area 12-bit integer codes required")
    settings = {"schema": "yblod.colour-frame-config.v1",
        "composer_report_sha256": verified["composer_report_sha256"], "source_dm": verified["source_dm"],
        "source_association": ASSOCIATION, "source_identity": verified["identity"],
        "source_provenance": verified["provenance"], "active_rectangle": verified["active_rectangle"],
        "target_ycc": target_ycc, "target_lms": target_lms, "target_offset": target_offset,
        "pq_policy": pq_policy, "outside_codes": outside_codes, "code_scale": code_scale,
        "chroma_expansion": "bilinear-left-diagnostic",
        "scope": "verified saved source-RPU association; explicit diagnostic target and unembedded transport, not licensed playback"}
    serialized = json.dumps(settings, indent=2, allow_nan=False) + "\n"
    with Path(destination).open("x") as handle:
        handle.write(serialized)
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--target-settings", type=Path, required=True,
                        help="JSON containing explicit target_ycc/lms/offset, pq_policy, outside_codes and code_scale")
    args = parser.parse_args()
    choices, _ = _json(args.target_settings.parent, args.target_settings.name)
    required = {"target_ycc", "target_lms", "target_offset", "pq_policy", "outside_codes", "code_scale"}
    if set(choices) != required:
        parser.error("target settings must contain exactly the six explicit target/policy fields")
    make_configuration(args.result, args.extraction, args.destination, **choices)


if __name__ == "__main__":
    main()
