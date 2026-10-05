#!/usr/bin/env python3
"""Bounded synthetic prepared-frame bundle; no film pixels or real RPU."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def make_demo(directory, *, width=512, height=256, chunk_samples=4096):
    for value, name in ((width, "width"), (height, "height")):
        if type(value) is not int or value % 2 or not 2 <= value <= 4096:
            raise ValueError(f"{name} must be an even integer in 2..4096")
    if type(chunk_samples) is not int or not 1 <= chunk_samples <= 65536:
        raise ValueError("chunk_samples must be integer in 1..65536")
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    identity = {"frame_id": f"synthetic-stream-{width}x{height}", "pts": 0, "time_base": [1, 24]}
    polynomial = {"pivots": [0, 512, 1023], "segments": [
        {"method": "polynomial", "coefficients": [131072, 524288, 262144]},
        {"method": "polynomial", "coefficients": [0, 1 << 20]},
    ]}
    mmr = {"pivots": [0, 1023], "segments": [{"method": "mmr", "constant": 1 << 18,
        "coefficients": [[1 << 18, 1 << 18, 0, 1 << 17, -(1 << 16), 0, 1 << 18],
                         [0, 1 << 15, 0, 0, 0, 0, -(1 << 14)],
                         [0, 0, 1 << 14, 0, 0, 0, 1 << 13]]}]}
    manifest = {
        "schema": "yblod.composer-frame.v1", "width": width, "height": height,
        "format": "yuv420p-u16le-lsb", "transfer": "pq", "chroma_location": "left",
        "preparation": "Synthetic already-aligned native layers and explicit synthetic MMR guide; no resampling.",
        "bl": dict(identity, planes={c: f"bl_{c}.u16le" for c in ("Y", "Cb", "Cr")}),
        "el": dict(identity, planes={c: f"el_{c}.u16le" for c in ("Y", "Cb", "Cr")}),
        "mmr_luma": "guide.u16le",
        "metadata": dict(identity, bl_bit_depth=10, el_bit_depth=10, output_bit_depth=12,
            coefficient_log2_denom=20, disable_residual=False, mappings=[polynomial, mmr, polynomial],
            nlq_method="linear_deadzone", nlq=[
                {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1025},
                {"offset": 512, "slope": 17, "threshold": 11, "maximum": 1024},
                {"offset": 512, "slope": 512, "threshold": 128, "maximum": 0},
            ]),
    }
    definitions = {
        "bl_Y.u16le": (width * height, 17, 3, False),
        "bl_Cb.u16le": (width * height // 4, 31, 7, False),
        "bl_Cr.u16le": (width * height // 4, 47, 11, False),
        "guide.u16le": (width * height // 4, 13, 7, False),
        "el_Y.u16le": (width * height, 1, 0, True),
        "el_Cb.u16le": (width * height // 4, 1, 2, True),
        "el_Cr.u16le": (width * height // 4, 1, 4, True),
    }
    hashes = {}
    for filename, (count, stride, offset, enhancement) in definitions.items():
        digest = hashlib.sha256()
        with (directory / filename).open("xb") as output:
            for start in range(0, count, chunk_samples):
                stop = min(count, start + chunk_samples)
                values = [(512 + (i + offset) % 9 - 4) if enhancement
                          else (i * stride + offset) % 1024 for i in range(start, stop)]
                data = struct.pack("<" + "H" * len(values), *values)
                output.write(data)
                digest.update(data)
        hashes[filename] = digest.hexdigest()
    (directory / "frame.json").write_text(json.dumps(manifest, indent=2) + "\n")
    evidence = {"schema": "yblod.synthetic-streaming-input.v1", "status": "complete",
                "scope": "synthetic arithmetic fixture, not conforming RPU or film",
                "width": width, "height": height,
                "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "input_sha256": hashes,
                "manifest_sha256": hashlib.sha256((directory / "frame.json").read_bytes()).hexdigest()}
    (directory / "synthetic.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=256)
    args = parser.parse_args()
    make_demo(args.directory, width=args.width, height=args.height)
