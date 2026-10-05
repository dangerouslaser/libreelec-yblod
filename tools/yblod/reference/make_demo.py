#!/usr/bin/env python3
"""Create a tiny, synthetic input bundle. No movie material or Dolby RPU is used."""
import argparse
import copy
import json
from pathlib import Path
import struct

from reference import SCHEMA


def make_demo(directory):
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    identity = {"frame_id": "synthetic-0", "pts": 0, "time_base": [1, 24]}
    mapping = {"pivots": [0, 1023], "segments": [
        {"method": "polynomial", "coefficients": [0, 1 << 20]}]}
    manifest = {
        "schema": SCHEMA, "width": 4, "height": 2,
        "format": "yuv420p-u16le-lsb", "transfer": "pq", "chroma_location": "left",
        "preparation": "Synthetic already-aligned BL/EL; no scaling; no MMR luma required.",
        "bl": dict(identity, planes={"Y": "bl_Y.u16le", "Cb": "bl_Cb.u16le", "Cr": "bl_Cr.u16le"}),
        "el": dict(identity, planes={"Y": "el_Y.u16le", "Cb": "el_Cb.u16le", "Cr": "el_Cr.u16le"}),
        "metadata": dict(identity, bl_bit_depth=10, el_bit_depth=10, output_bit_depth=12,
                         coefficient_log2_denom=20, disable_residual=False,
                         mappings=[copy.deepcopy(mapping) for _ in range(3)],
                         nlq_method="linear_deadzone", nlq=[
                             {"offset": 512, "slope": 1024, "threshold": 0, "maximum": 1 << 19}
                             for _ in range(3)])}
    planes = {"bl_Y": [0, 1, 511, 512, 513, 1022, 1023, 512],
              "bl_Cb": [256, 768], "bl_Cr": [384, 640],
              "el_Y": [512, 512, 512, 512, 512, 512, 512, 513],
              "el_Cb": [512, 512], "el_Cr": [512, 512]}
    for name, samples in planes.items():
        (directory / f"{name}.u16le").write_bytes(struct.pack(f"<{len(samples)}H", *samples))
    (directory / "frame.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new input directory")
    args = parser.parse_args()
    make_demo(args.directory)
    print(args.directory / "frame.json")
