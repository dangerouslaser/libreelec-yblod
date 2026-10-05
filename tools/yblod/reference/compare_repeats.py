#!/usr/bin/env python3
"""Read-only comparison of frozen-buffer rereads and fresh paused-frame captures.

No output correction, device access, or timestamp-to-frame inference. An
external visible-frame association and explicit active rectangle are required.
All raw bytes are compared; active transport codes use bounded 32-row strips.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import numpy as np

from compare_output import decode_ce, matrices
from diagnose_frame import packet_copies, read_strip
from extract_frame import digest, save_json
from output_frame import TARGET_YCC, TARGET_LMS, TARGET_OFFSET
from transport_precision import new_accumulator, update, finish

STRIP_ROWS = 32


def rectangle_valid(rectangle, width, height):
    if len(rectangle) != 4 or any(type(v) is not int for v in rectangle):
        raise ValueError("four integer active-rectangle coordinates required")
    l, t, r, b = rectangle
    if (not 0 <= l < r <= width or not 0 <= t < b <= height or l % 2 or r % 2
            or t*width+l < 6144):
        raise ValueError("invalid active rectangle or overlap with embedded metadata")


def capture_metadata(path, width, height):
    rows = (6144+width-1)//width
    if rows > height:
        raise ValueError("capture cannot contain both metadata packets")
    with Path(path).open("rb") as handle:
        initial = decode_ce(read_strip(handle, 0, rows, width, "u1"))
    metadata = packet_copies(*initial)
    metadata["packet_sha256"] = [hashlib.sha256(bytes.fromhex(value)).hexdigest()
                                for value in metadata.pop("packet_hex")]
    for actual, expected in zip(matrices(*initial), (TARGET_YCC, TARGET_OFFSET, TARGET_LMS)):
        if not np.array_equal(actual, expected):
            raise ValueError("capture transport colour matrices differ from supported coordinates")
    return metadata


def compact(accumulator):
    result = finish(accumulator)
    return {"samples": result["samples"], "changed_samples": result["samples"]-result["events"]["identical"],
            "mean_signed_codes": result["signed_decomposition"]["mean_delta12_codes"],
            "mean_absolute_codes": result["absolute_errors_not_additive"]["mean_delta12_codes"],
            "maximum_absolute_codes": result["maximum_absolute_delta12_codes"],
            "rmse_codes": result["rmse_delta12_codes"],
            "signed_decomposition": result["signed_decomposition"],
            "absolute_errors_not_additive": result["absolute_errors_not_additive"]}


def compare_pair(first, second, width, height, rectangle):
    """Positive signed error means second-read code minus first-read code."""
    rectangle_valid(rectangle, width, height)
    if width*3 % 8 or min(width, height) < 1:
        raise ValueError("word-aligned rows required")
    expected_bytes = width*height*3
    if any(Path(path).stat().st_size != expected_bytes for path in (first, second)):
        raise ValueError("raw capture dimensions/byte count mismatch")
    metadata = [capture_metadata(path, width, height) for path in (first, second)]
    l, t, r, b = rectangle
    totals = {channel: {group: new_accumulator() for group in ("all", "even_row", "odd_row")}
              for channel in ("I", "P", "T")}
    hashes = [hashlib.sha256(), hashlib.sha256()]
    changed_bytes, first_byte, metadata_lsb_changes, other_payload_changes = 0, None, 0, 0
    with ExitStack() as stack:
        handles = [stack.enter_context(Path(path).open("rb")) for path in (first, second)]
        for start in range(0, height, STRIP_ROWS):
            stop = min(height, start+STRIP_ROWS)
            raw = [read_strip(handle, start, stop, width, "u1") for handle in handles]
            for value, checksum in zip(raw, hashes):
                checksum.update(value.tobytes())
            different = raw[0] != raw[1]
            count = int(np.count_nonzero(different))
            if count and first_byte is None:
                first_byte = start*width*3 + int(np.flatnonzero(different.reshape(-1))[0])
            changed_bytes += count
            decoded = [decode_ce(value) for value in raw]
            i_change = decoded[0][0] != decoded[1][0]
            c_xor = decoded[0][1] ^ decoded[1][1]
            in_metadata = np.arange(start*width, stop*width).reshape(stop-start, width) < 6144
            metadata_lsb_changes += int(np.count_nonzero(in_metadata & ((c_xor & 1) != 0)))
            # Only embedded chroma bit0 in the first6144 pixels is metadata.
            # Intensity/other chroma-bit changes there are not called metadata-only.
            other_payload_changes += int(np.count_nonzero(i_change | ((c_xor & 0xFFFE) != 0)
                                                         | (~in_metadata & (c_xor != 0))))
            a, z = max(start, t), min(stop, b)
            if a >= z:
                continue
            selected = slice(a-start, z-start)
            rows = np.arange(a, z)[:, None]
            for channel, plane, columns in (("I", 0, slice(l, r)), ("P", 1, slice(l, r, 2)),
                                             ("T", 1, slice(l+1, r, 2))):
                before, after = [value[plane][selected, columns] for value in decoded]
                masks = {"all": np.ones(before.shape, bool),
                         "even_row": np.broadcast_to(rows % 2 == 0, before.shape),
                         "odd_row": np.broadcast_to(rows % 2 == 1, before.shape)}
                for group, mask in masks.items():
                    update(totals[channel][group], after[mask], before[mask])
    channels = {channel: {group: compact(value) for group, value in groups.items()}
                for channel, groups in totals.items()}
    picture_changes = sum(channel["all"]["changed_samples"] for channel in channels.values())
    byte_equal = changed_bytes == 0
    checksum_equal = hashes[0].digest() == hashes[1].digest()
    if byte_equal != checksum_equal or byte_equal != (first_byte is None):
        raise ValueError("raw byte/hash equality accounting disagrees")
    if byte_equal and (picture_changes or metadata_lsb_changes or other_payload_changes):
        raise ValueError("identical bytes produced a nonzero decoded difference")
    for channel, divisor in (("I", 1), ("P", 2), ("T", 2)):
        groups = channels[channel]
        if (groups["all"]["samples"] != (r-l)*(b-t)//divisor or
                groups["even_row"]["samples"]+groups["odd_row"]["samples"] != groups["all"]["samples"]):
            raise ValueError("active/parity sample count mismatch")
    classification = ("byte_identical" if byte_equal else "active_picture_changed" if picture_changes
                      else "metadata_only" if other_payload_changes == 0
                      else "inactive_or_nonmetadata_payload_changed")
    return {"first_sha256": hashes[0].hexdigest(), "second_sha256": hashes[1].hexdigest(),
            "compared_bytes": expected_bytes, "byte_identical": byte_equal,
            "changed_bytes": changed_bytes, "first_difference_byte": first_byte,
            "classification": classification, "active_picture_changed": bool(picture_changes),
            "embedded_metadata_lsb_changed_samples": metadata_lsb_changes,
            "nonmetadata_payload_changed_pixel_slots": other_payload_changes,
            "metadata": {"first": metadata[0], "second": metadata[1],
                         "packet_bytes_identical": metadata[0]["packet_sha256"] == metadata[1]["packet_sha256"]},
            "channels": channels}


def checked_file(root, record, expected_bytes):
    path = (root/record["file"]).resolve()
    if (Path(record["file"]).is_absolute() or not path.is_relative_to(root) or
            record["bytes"] != expected_bytes or path.stat().st_size != expected_bytes or
            digest(path) != record["sha256"]):
        raise ValueError("capture file path, byte count or hash mismatch")
    return path


def check_driver_claims(manifest, cycle):
    """Absent evidence stays unknown; contradictory availability is rejected."""
    present = "driver_dump" in cycle
    if not present and "driver_vs_first_comparison" in cycle:
        raise ValueError("driver comparison claimed without a driver dump")
    sync = cycle.get("dma_sync")
    if "dma_sync" in cycle:
        if not isinstance(sync, dict):
            raise ValueError("DMA synchronization record must be an object")
        available = sync.get("driver_dump_available")
        if available is not None and (type(available) is not bool or available != present):
            raise ValueError("DMA record contradicts driver dump availability")
        if sync.get("status") == "driver_dump_observed" and not present:
            raise ValueError("observed driver dump claimed without its file")
    if (not present and "allow_unverified_dma_sync" in manifest
            and manifest["allow_unverified_dma_sync"] is not True):
        raise ValueError("complete capture lacks driver dump despite strict DMA policy")


def readback_evidence(manifest, drivers, driver_pairs, same_pairs):
    missing = [i for i, path in enumerate(drivers) if path is None]
    coverage = "none" if len(missing) == len(drivers) else "partial" if missing else "all"
    unverified = [cycle["cycle_index"] for cycle in manifest["cycles"]
                  if cycle.get("dma_sync", {}).get("status") == "unverified"]
    limits = ["These are empirical comparisons of captured bytes, not proof that DMA readback reflects current hardware output.",
              "Captured software, driver timestamps and paused-player state are report provenance; this analyzer does not independently attest them."]
    if missing:
        limits.insert(0, "Driver-dump evidence is missing for some or all cycles: identical physical reads cannot rule out stale cache data.")
    else:
        limits.append("Available driver dumps are independently compared, but a matching dump alone is not independently instrumented proof of DMA coherency.")
    if any(not pair["comparison"]["byte_identical"] for pair in driver_pairs):
        limits.insert(0, "At least one driver dump differs from its physical read; fresh-buffer comparisons have unresolved readback disagreement.")
    if any(not pair["comparison"]["byte_identical"] for pair in same_pairs):
        limits.insert(0, "At least one frozen-buffer reread differs; fresh-buffer changes cannot be interpreted independently of readback instability.")
    return {"scope": "empirical captured-byte stability only", "driver_dump_coverage": coverage,
            "cycles_without_driver_dump": missing, "cycles_declaring_dma_sync_unverified": unverified,
            "cycles_without_dma_sync_record": [cycle["cycle_index"] for cycle in manifest["cycles"] if "dma_sync" not in cycle],
            "dma_coherency_proven": False, "software_state_independently_attested": False,
            "allow_unverified_dma_sync_as_reported": manifest.get("allow_unverified_dma_sync"),
            "summary_limitations": limits}


def analyze(manifest_path, identity_path, rectangle):
    manifest_path, identity_path = Path(manifest_path).resolve(), Path(identity_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    identity = json.loads(identity_path.read_text())
    if manifest["schema"] != "yblod.capture-repeat.v1" or manifest["status"] != "complete":
        raise ValueError("complete capture-repeat report required")
    if "allow_unverified_dma_sync" in manifest and type(manifest["allow_unverified_dma_sync"]) is not bool:
        raise ValueError("allow_unverified_dma_sync must be a boolean when present")
    source_hash = identity["source_sha256"]
    if (not isinstance(source_hash, str) or len(source_hash) != 64 or
            any(c not in "0123456789abcdef" for c in source_hash) or
            type(identity["visible_frame_number"]) is not int or identity["visible_frame_number"] < 0 or
            type(identity["pts_us"]) is not int):
        raise ValueError("explicit visible-frame/source association required")
    width, height = manifest["width"], manifest["height"]
    if any(type(v) is not int or v <= 0 for v in (width, height)) or width*3 % 8:
        raise ValueError("positive dimensions with word-aligned rows required")
    rectangle_valid(rectangle, width, height)
    cycles = manifest["cycles"]
    if len(cycles) < 2 or [c["cycle_index"] for c in cycles] != list(range(len(cycles))):
        raise ValueError("at least two consecutively numbered fresh capture cycles required")
    files, drivers, used = [], [], set()
    for cycle in cycles:
        check_driver_claims(manifest, cycle)
        pair = [checked_file(manifest_path.parent, cycle[key], width*height*3) for key in ("first_read", "second_read")]
        if any(path in used for path in pair) or pair[0] == pair[1]:
            raise ValueError("capture reads must name distinct files")
        used.update(pair)
        files.append(pair)
        driver = checked_file(manifest_path.parent, cycle["driver_dump"], width*height*3) if "driver_dump" in cycle else None
        if driver is not None:
            if driver in used:
                raise ValueError("driver dump must name a distinct file")
            used.add(driver)
        drivers.append(driver)
    same, fresh, driver_pairs = [], [], []
    for index, (cycle, pair) in enumerate(zip(cycles, files)):
        comparison = compare_pair(*pair, width, height, rectangle)
        if (comparison["first_sha256"] != cycle["first_read"]["sha256"] or
                comparison["second_sha256"] != cycle["second_read"]["sha256"]):
            raise ValueError("capture changed during analysis")
        claimed = cycle.get("same_buffer_comparison")
        if claimed is not None and (claimed["byte_identical"] != comparison["byte_identical"] or
                                    claimed["first_difference_offset"] != comparison["first_difference_byte"] or
                                    claimed["compared_bytes"] != comparison["compared_bytes"]):
            raise ValueError("capture-side reread claim disagrees with independent comparison")
        same.append({"cycle_index": index, "buffer": cycle["buffer"], "comparison": comparison})
        if drivers[index] is not None:
            comparison = compare_pair(drivers[index], pair[0], width, height, rectangle)
            if (comparison["first_sha256"] != cycle["driver_dump"]["sha256"] or
                    comparison["second_sha256"] != cycle["first_read"]["sha256"]):
                raise ValueError("driver dump changed during analysis")
            claimed = cycle.get("driver_vs_first_comparison")
            if claimed is not None and (claimed["byte_identical"] != comparison["byte_identical"] or
                                        claimed["first_difference_offset"] != comparison["first_difference_byte"] or
                                        claimed["compared_bytes"] != comparison["compared_bytes"]):
                raise ValueError("capture-side driver/readback claim disagrees with independent comparison")
            driver_pairs.append({"cycle_index": index, "buffer": cycle["buffer"], "comparison": comparison})
        if index:
            comparison = compare_pair(files[0][0], pair[0], width, height, rectangle)
            if (comparison["first_sha256"] != cycles[0]["first_read"]["sha256"] or
                    comparison["second_sha256"] != cycle["first_read"]["sha256"]):
                raise ValueError("fresh capture changed during analysis")
            fresh.append({"first_cycle": 0, "second_cycle": index, "comparison": comparison})
    evidence = readback_evidence(manifest, drivers, driver_pairs, same)
    return {"schema": "yblod.capture-repeat-comparison.v1", "status": "complete",
            "readback_evidence": evidence, "summary_limitations": evidence["summary_limitations"],
            "identity": identity, "identity_basis": "caller-supplied visible-counter/source association; not inferred from driver PTS",
            "active_rectangle": rectangle, "width": width, "height": height,
            "manifest_sha256": digest(manifest_path), "identity_file_sha256": digest(identity_path),
            "capture_provenance": manifest, "processing_strip_rows": STRIP_ROWS,
            "same_frozen_buffer_pairs": same, "fresh_buffer_pairs": fresh,
            "driver_dump_vs_first_read_pairs": driver_pairs,
            "driver_dump_comparisons_available": len(driver_pairs),
            "all_available_driver_dumps_match_first_read": all(x["comparison"]["byte_identical"] for x in driver_pairs) if driver_pairs else None,
            "all_same_buffer_reads_byte_identical": all(x["comparison"]["byte_identical"] for x in same),
            "all_fresh_reads_byte_identical": all(x["comparison"]["byte_identical"] for x in fresh),
            "any_fresh_active_picture_changed": any(x["comparison"]["active_picture_changed"] for x in fresh),
            "direction": "second read/cycle minus first read/cycle; row parity is absolute frame-row parity",
            "metadata_only_definition": "Only embedded C-bit0 within first6144 pixel slots changed; all three packet copies validate, all other bits identical",
            "runtime": {"numpy_version": np.__version__}, "implementation_sha256": digest(Path(__file__)),
            "caveats": ["Same frozen-buffer identity and paused-picture state are inherited from capture provenance, not proved by pixel hashes.",
                        "Capture timestamps/software state are recorded, not used to invent source-frame identity.",
                        "Stable results do not exclude spatial dithering; varying results do not establish temporal dithering.",
                        "A loopback capture is not an independent HDMI-wire measurement.",
                        "Explicit active rectangle and supplied visible-frame association must be independently checked by the caller.",
                        "Any unstable same-buffer reread weakens interpretation of fresh-buffer changes.",
                        "Only aggregate differences are reported; no corrections, fitted offsets or reconstructed images."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_report", type=Path)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--active-rectangle", type=int, nargs=4, required=True, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = analyze(args.capture_report, args.identity, args.active_rectangle)
        save_json(args.report, report)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"repeat comparison: {error}\n")
    print(json.dumps({"report": str(args.report), "stable_rereads": report["all_same_buffer_reads_byte_identical"],
                      "fresh_picture_changes": report["any_fresh_active_picture_changed"],
                      "driver_dump_coverage": report["readback_evidence"]["driver_dump_coverage"],
                      "dma_coherency_proven": False}))


if __name__ == "__main__":
    main()
