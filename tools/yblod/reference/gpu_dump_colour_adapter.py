#!/usr/bin/env python3
"""Bind real GPU reconstructed planes to verified historical prepared inputs.

Only reconstructed stages are emitted. No mapped, residual, sum, or colour
intermediate is copied from another producer. This is not live playback proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 << 20:
        raise ValueError("bounded regular JSON required")
    with path.open("rb") as stream:
        return json.load(stream)


def adapt(repo, baseline, extraction, fixture, dump, probe_report, destination):
    sys.path.insert(0, str(repo / "tools/yblod/reference"))
    import reference
    import colour_metadata
    old = read_json(baseline / "report.json")
    if old.get("schema") != "yblod.composer-result.v1" or old.get("status") != "complete":
        raise ValueError("completed historical composer required")
    manifest = old["input_manifest"]
    reference.validate(manifest)
    colour_metadata.load(baseline, extraction)
    width, height = manifest["width"], manifest["height"]
    if (width, height) != (3840, 2160) or manifest["metadata"]["output_bit_depth"] != 12:
        raise ValueError("this adapter currently qualifies only 4K/12bit")
    fixture_root = fixture.parent
    producer = read_json(fixture_root / "producer-result-private.json")
    args = read_json(fixture_root / "producer-arguments-private.json")
    required = ("decoder_metadata", "raw_rpu_exact", "el_active_planes_exact", "crc_requested")
    if producer.get("status") != "complete" or any(producer.get(k) is not True for k in required):
        raise ValueError("verified native metadata producer required")
    if producer.get("warning_or_error_logs") != 0 or producer["instructions_sha256"] != sha(fixture / "instructions.bin"):
        raise ValueError("native instructions producer differs")
    if sha(extraction / "frame.rpu.nal") != args["files"]["frame.rpu.nal"]:
        raise ValueError("native producer source RPU differs")
    if args["extraction_sha256"] != sha(extraction / "extraction.json"):
        raise ValueError("fixture source extraction differs")
    inputs = {}
    for name in ("bl_Y.u16le", "bl_Cb.u16le", "bl_Cr.u16le", "mmr_luma.u16le"):
        inputs[name] = sha(fixture / name)
        if inputs[name] != old["input_sha256"][name]:
            raise ValueError("actual GPU prepared base/guide differs from historical composer")
    # Decode P010 in bounded rows solely to verify every scaled EL sample is
    # precisely the historical low-aligned native10 input. No filter runs here.
    hashes = {c: hashlib.sha256() for c in ("Y", "Cb", "Cr")}
    packed = fixture / "scaled1.p010"
    if packed.stat().st_size != width * height * 3:
        raise ValueError("scaled P010 size differs")
    with packed.open("rb") as stream:
        for y in range(height + height // 2):
            raw = stream.read(width * 2)
            values = [x[0] for x in struct.iter_unpack("<H", raw)]
            if len(values) != width or any(v & 63 for v in values):
                raise ValueError("noncanonical MSB-aligned P010")
            native = [v >> 6 for v in values]
            if y < height:
                hashes["Y"].update(struct.pack("<" + "H" * width, *native))
            else:
                for c, parity in (("Cb", 0), ("Cr", 1)):
                    hashes[c].update(struct.pack("<" + "H" * (width // 2), *native[parity::2]))
        if stream.read(1):
            raise ValueError("extra packed input bytes")
    for c in hashes:
        if hashes[c].hexdigest() != old["input_sha256"]["el_" + c + ".u16le"]:
            raise ValueError("actual GPU scaled EL differs from historical composer")
    inputs["scaled1.p010"] = sha(packed)
    inputs["instructions.bin"] = sha(fixture / "instructions.bin")
    probe = read_json(probe_report)
    counts = [width * height, width * height // 4, width * height // 4]
    if probe.get("schema") != "yblod.native-gpu-composer-compare-probe.v1" or probe.get("status") != "complete":
        raise ValueError("completed actual GPU probe report required")
    if probe.get("counts") != counts or probe.get("raw_dump_requested") is not True:
        raise ValueError("GPU plane-count/dump declaration differs")
    if probe.get("raw_dump_format") != "u16le-native-grid-Y-then-Cb-then-Cr-no-padding":
        raise ValueError("GPU dump format differs")
    if dump.is_symlink() or dump.stat().st_size != sum(counts) * 2:
        raise ValueError("exact regular reconstructed dump required")
    pins = {"dump": sha(dump), "probe": sha(probe_report), "baseline": sha(baseline / "report.json")}
    destination.mkdir(mode=0o700)
    stages = {}
    with dump.open("rb") as stream:
        for channel, count in zip(("Y", "Cb", "Cr"), counts):
            name = "reconstructed_" + channel + ".u16le"
            minimum, maximum, remaining = 4095, 0, count * 2
            digest = hashlib.sha256()
            with (destination / name).open("xb") as target:
                while remaining:
                    data = stream.read(min(65536, remaining))
                    if not data or len(data) % 2:
                        raise ValueError("truncated reconstructed plane")
                    values = [x[0] for x in struct.iter_unpack("<H", data)]
                    if max(values) > 4095:
                        raise ValueError("reconstructed codes outside12bit")
                    minimum, maximum = min(minimum, min(values)), max(maximum, max(values))
                    digest.update(data)
                    target.write(data)
                    remaining -= len(data)
            stages["reconstructed_" + channel] = dict(file=name, samples=count,
                minimum=minimum, maximum=maximum, sha256=digest.hexdigest())
    if sha(dump) != pins["dump"] or sha(probe_report) != pins["probe"] or sha(baseline / "report.json") != pins["baseline"]:
        raise ValueError("GPU artifacts or source report changed")
    if any(sha(fixture / name) != pin for name, pin in inputs.items()):
        raise ValueError("actual GPU inputs changed")
    report = dict(schema="yblod.composer-result.v1", status="complete",
        scope="actual GPU reconstructed-plane view only; no intermediate stages invented; historical preparation, not live output",
        input_manifest=manifest, stages=stages, input_sha256=inputs,
        implementation_sha256=sha(Path(__file__)),
        gpu_source_provenance=dict(raw_dump_sha256=pins["dump"], probe_report_sha256=pins["probe"],
            historical_manifest_report_sha256=pins["baseline"],
            native_producer_report_sha256=sha(fixture_root / "producer-result-private.json"),
            actual_gpu_input_files_rehashed=True, packed_el_exact_historical_inputs=True,
            source_rpu_exact=True, source_association_not_authentication=True))
    with (destination / "report.json").open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    colour_metadata.load(destination, extraction)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("repo", "baseline", "extraction", "fixture", "dump", "probe-report", "destination"):
        parser.add_argument("--" + name, required=True, type=Path)
    a = parser.parse_args()
    adapt(*(getattr(a, n).resolve() for n in
        ("repo", "baseline", "extraction", "fixture", "dump", "probe_report", "destination")))
    print("GPU reconstructed-plane report bound to verified same prepared inputs.")
