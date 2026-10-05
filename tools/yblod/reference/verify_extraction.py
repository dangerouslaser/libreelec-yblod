#!/usr/bin/env python3
"""Verify saved plane/metadata hashes and repeat decoding with one CPU thread."""
import argparse
import hashlib
import json
from pathlib import Path

from extract_frame import (Commands, decoded_picture_index, digest, save_json,
                           verify_picture_geometry, verify_picture_window)
from import_rpu import normalize


def verify(directory):
    directory = Path(directory).resolve()
    extraction = json.loads((directory / "extraction.json").read_text())
    composition = json.loads((directory / "composition.json").read_text())
    if extraction["status"] != "complete" or not extraction["rpu_matches_source_packet_and_global_index"]:
        raise ValueError("extraction is not complete and packet-verified")
    for filename, expected in (("frame.rpu.bin", extraction["rpu_sha256"]),
                               ("rpu.json", extraction["rpu_json_sha256"]),
                               ("extraction.json", composition["source_extraction_sha256"])):
        if digest(directory / filename) != expected:
            raise ValueError(f"changed file: {filename}")
    if digest(extraction["source"]) != extraction["source_sha256"]:
        raise ValueError("source movie changed since extraction")
    if digest(directory / "source-packet.bin") != extraction["source_packet_sha256"]:
        raise ValueError("saved source packet changed")
    metadata = composition["metadata"]
    identity = {"frame_id": f"{extraction['source_sha256']}:{extraction['source_packet_index_zero_based']}",
                "pts": extraction["pts"], "time_base": extraction["time_base"]}
    if normalize(json.loads((directory / "rpu.json").read_text()), identity) != metadata:
        raise ValueError("normalized instructions do not reproduce exactly")
    output = directory / "verification"
    output.mkdir(exist_ok=False)
    commands = Commands(output)
    result = {"schema": "yblod.extraction-verification.v1", "status": "complete",
              "extraction_sha256": digest(directory / "extraction.json"),
              "composition_sha256": digest(directory / "composition.json"),
              "source_checksum_verified": True, "metadata_normalization_exact": True,
              "layers": {}, "verifier_sha256": digest(__file__)}
    for label, layer in extraction["layers"].items():
        plane_hash = hashlib.sha256()
        for channel in ("Y", "Cb", "Cr"):
            plane = layer["planes"][channel]
            data = (directory / plane["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != plane["sha256"] or len(data) != 2 * plane["samples"]:
                raise ValueError(f"{label}/{channel}: plane integrity failed")
            plane_hash.update(data)
        if plane_hash.hexdigest() != layer["raw_sha256"] or digest(directory / f"{label}.yuv") != layer["raw_sha256"]:
            raise ValueError(f"{label}: saved planes do not reproduce the raw frame")
        window = directory / f"{label}-decode-window.hevc"
        if digest(window) != layer["window_sha256"]:
            raise ValueError(f"{label}: decode window changed")
        if "window_mapping" in layer:
            mapping = layer["window_mapping"]
            verify_picture_window(directory / ("BL.hevc" if label == "bl" else "EL.hevc"), window, mapping)
            if (mapping["packets"][-1]["source_packet_index"] != extraction["source_packet_index_zero_based"]
                    or mapping["packets"][-1]["layer_coded_index"] != layer["decode_index_zero_based"]
                    or mapping["target_window_byte"] != layer["window_target_byte"]):
                raise ValueError(f"{label}: decode-window mapping does not preserve target identity")
            target_position = layer["window_target_byte"]
        else:
            # Earlier unfiltered bundles retain their original offset identity.
            target_position = int(layer["decoder_packet"]["pos"]) - layer["window_start_byte"]
        if str(layer["decoded_frame"].get("pkt_pos")) != str(target_position):
            raise ValueError(f"{label}: saved decoded picture does not identify the source packet")
        # Decoder presentation order is not container/coded packet order. Resolve
        # it independently with one thread, including B-picture delayed output.
        decoded = commands.probe(f"repeat-{label}-frames", ["-threads", "1", "-err_detect", "explode",
            "-show_frames", "-show_entries", "frame=pkt_pos,pkt_size,pict_type,width,height,pix_fmt,chroma_location"], window)["frames"]
        if (output / f"repeat-{label}-frames.stderr").read_text().strip():
            raise ValueError(f"{label}: single-thread packet-position probe reported a decode error")
        presentation_index = decoded_picture_index(decoded, target_position)
        verify_picture_geometry(layer["decoded_frame"], decoded[presentation_index])
        if presentation_index != layer["presentation_index_zero_based"]:
            raise ValueError(f"{label}: decoder thread counts disagree about presentation order")
        raw = output / f"{label}-single-thread.yuv"
        commands.run(f"repeat-{label}", ["ffmpeg", "-nostdin", "-v", "error", "-n", "-xerror",
            "-threads", "1", "-err_detect", "explode", "-i", str(window), "-map", "0:v:0",
            "-vf", f"select=eq(n\\,{presentation_index})", "-filter_threads", "1",
            "-frames:v", "1", "-fps_mode", "passthrough", "-c:v", "rawvideo", "-threads:v", "1",
            "-pix_fmt", "+yuv420p10le", "-f", "rawvideo", str(raw)])
        if digest(raw) != layer["raw_sha256"]:
            raise ValueError(f"{label}: single-thread decode differs from extraction")
        result["layers"][label] = {"plane_hashes_valid": True, "planes_reassemble_exactly": True,
                                   "single_and_four_thread_decodes_identical": True,
                                   "packet_position_verified_with_both_thread_counts": True,
                                   "window_reconstructed_from_source_mapping": "window_mapping" in layer,
                                   "sha256": layer["raw_sha256"]}
    result["commands"] = commands.commands
    save_json(output / "verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        verify(args.directory)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"verification: {error}\n")
    print("Saved planes and instructions verified; one- and four-thread decodes are byte-identical.")
