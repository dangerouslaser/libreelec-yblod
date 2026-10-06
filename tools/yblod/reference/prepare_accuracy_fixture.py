#!/usr/bin/env python3
"""Prepare private same-input composer fixtures; does not execute GPU or decode.

Reuse the source-verified decoder-window derivation. The prepared filter policy
is recorded, not silently equated with the currently deployed playback policy.
Run the existing guarded run_private.py afterwards in a 512 MiB/no-swap scope.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("bounded regular manifest required")
    return json.loads(path.read_text())


def verify_plane(path, record):
    width, height = record["width"], record["height"]
    if (type(width) is not int or type(height) is not int or
            not 0 < width <= 3840 or not 0 < height <= 2160):
        raise ValueError("bounded plane geometry required")
    if (path.is_symlink() or not path.is_file() or
            path.stat().st_size != width * height * 2 or digest(path) != record["sha256"]):
        raise ValueError("plane extent or SHA differs")


def main():
    parser = argparse.ArgumentParser()
    for name in ("repo", "source", "prepared", "out", "decoder", "packer"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve(strict=True)
             for name in ("repo", "source", "prepared", "out", "decoder", "packer")}
    out = paths["out"]
    if out.stat().st_mode & 0o077 or out.stat().st_uid != os.geteuid() or any(out.iterdir()):
        raise ValueError("fresh private output directory required")
    source, prepared = paths["source"], paths["prepared"]
    extraction = manifest(source / "extraction.json")
    frame = manifest(prepared / "frame.json")
    if extraction.get("status") != "complete" or not extraction.get("rpu_matches_source_packet_and_global_index"):
        raise ValueError("verified source/RPU extraction required")
    identity = f"{extraction['source_sha256']}:{extraction['source_packet_index_zero_based']}"
    for layer in ("bl", "el"):
        if frame[layer]["frame_id"] != identity or frame[layer]["pts"] != extraction["pts"]:
            raise ValueError("prepared/source association differs")
        if frame[layer]["time_base"] != extraction["time_base"]:
            raise ValueError("prepared/source time base differs")
    el = extraction["layers"]["el"]
    if (el["width"], el["height"]) != (1920, 1080) or not el["source_packet_vcl_identical"]:
        raise ValueError("verified 1080p enhancement layer required")
    details = frame["preparation_details"]
    if details["source_extraction_sha256"] != digest(source / "extraction.json"):
        raise ValueError("prepared extraction SHA differs")
    stages = details["stages"]
    for stage in ("bl_Y", "bl_Cb", "bl_Cr", "mmr_luma", "el_Y", "el_Cb", "el_Cr"):
        record = stages[stage]
        if record["file"] != stage + ".u16le":
            raise ValueError("prepared stage filename differs")
        verify_plane(prepared / record["file"], record)
    for channel in ("Y", "Cb", "Cr"):
        record = el["planes"][channel]
        if Path(record["file"]).name != record["file"]:
            raise ValueError("source plane basename required")
        scale = 1 if channel == "Y" else 2
        verify_plane(source / record["file"], dict(record,
                     width=el["width"] // scale, height=el["height"] // scale))
    sys.path.insert(0, str(paths["repo"] / "tools/yblod/reference"))
    from derive_decoder_window_fixture import derive, verify_aud_boundary
    nal = source / "frame.rpu.nal"
    position = int(el["decoder_packet"]["pos"]) - el["window_start_byte"]
    size = int(el["decoder_packet"]["size"])
    if "window_target_byte" in el:
        mapped = [p for p in el["window_mapping"]["packets"]
                  if p["source_packet_index"] == extraction["source_packet_index_zero_based"]
                  and p["action"] == "copy"]
        if len(mapped) != 1 or mapped[0]["window_byte"] != el["window_target_byte"]:
            raise ValueError("mapped target packet identity differs")
        if mapped[0]["size"] != size:
            raise ValueError("mapped target packet size differs")
        # A verified CRA/RASL-dropped window is not contiguous source bytes.
        # Its explicit mapping, rather than source-position subtraction, owns
        # the target offset. Decoder pixel hashes still independently verify it.
        position = mapped[0]["window_byte"]
    derived = out / "el-window-canonical.hevc"
    result = derive(source / "el-decode-window.hevc", nal, derived,
                    window_sha256=el["window_sha256"], canonical_nal_sha256=digest(nal),
                    packet_position=position, packet_size=size)
    boundary = verify_aud_boundary(derived, window_sha256=result["derived_window_sha256"],
                                  legacy_position=position, legacy_size=size)

    def copy(src, name, expected=None):
        if src.is_symlink() or not src.is_file() or not 0 < src.stat().st_size <= 128 * 1024 * 1024:
            raise ValueError("bounded regular source required")
        before = digest(src)
        if expected is not None and before != expected:
            raise ValueError("source SHA differs")
        dst = out / name
        if dst.exists():
            raise ValueError("fresh output path required")
        shutil.copyfile(src, dst)
        dst.chmod(0o600)
        if digest(dst) != before or digest(src) != before:
            raise ValueError("source/copy changed")

    copy(nal, "frame.rpu.nal")
    planes = []
    for channel in ("Y", "Cb", "Cr"):
        plane = el["planes"][channel]
        copy(source / plane["file"], "decoded_el_" + channel + ".u16le", plane["sha256"])
        planes.append(plane["sha256"])
    for name in ("bl_Y.u16le", "bl_Cb.u16le", "bl_Cr.u16le", "mmr_luma.u16le",
                 "el_Y.u16le", "el_Cb.u16le", "el_Cr.u16le"):
        copy(prepared / name, name, stages[name[:-6]]["sha256"])
    for argument, name in (("decoder", "native_decoder_ingestion"), ("packer", "native_p010_fixture")):
        copy(paths[argument], name)
        (out / name).chmod(0o700)
    record = dict(frame=extraction["source_packet_index_zero_based"],
                  scope="same-input arithmetic only; prepared policy is not live playback proof",
                  preparation_policy=frame.get("preparation_details", {}).get("policy"),
                  extraction_sha256=digest(source / "extraction.json"),
                  prepared_manifest_sha256=digest(prepared / "frame.json"),
                  argv=[str(derived), str(out / "frame.rpu.nal"),
                        str(el["presentation_index_zero_based"]), str(boundary["canonical_aud_position"]),
                        str(boundary["canonical_packet_size"]), result["derived_window_sha256"],
                        *planes, str(out / "instructions.bin")])
    record["files"] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
    with (out / "producer-arguments-private.json").open("x") as stream:
        json.dump(record, stream, allow_nan=False)
    (out / "producer-arguments-private.json").chmod(0o600)
    print("Private fixture staged; decode, pack and GPU comparison have not run.")


if __name__ == "__main__":
    main()
