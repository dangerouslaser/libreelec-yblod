#!/usr/bin/env python3
"""Compare a completed same-input DVBridge capture pair; requires NumPy.

Reports native 12-bit transport differences, not a judgment of picture accuracy.
No colour conversion, alignment, or fitted offset is applied to the comparison.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from dvtunnel import W, H, crc32_mpeg2, load_kodi


def metadata_packets(y, c, count):
    if not 1 <= count <= W * H // 3072:
        raise ValueError("Invalid metadata packet count")
    parity = np.array([i.bit_count() & 1 for i in range(4096)], dtype=np.uint8)
    result = []
    for number in range(count):
        start = number * 3072
        yy = y.reshape(-1)[start:start + 1024]
        cc = c.reshape(-1)[start:start + 1024]
        bits = (cc & 1) ^ parity[cc >> 1] ^ parity[yy]
        packet = np.packbits(bits.astype(np.uint8)).tobytes()
        if crc32_mpeg2(packet[:124]) != int.from_bytes(packet[124:], "big"):
            raise ValueError(f"Metadata packet {number} failed CRC")
        result.append(packet)
    return result


def stats(release, direct):
    difference = direct.astype(np.int32) - release.astype(np.int32)
    magnitude = np.abs(difference)
    return {
        "samples": int(difference.size),
        "mean_signed_codes": float(difference.mean()),
        "mean_absolute_codes": float(magnitude.mean()),
        "rmse_codes": float(np.sqrt(np.mean(difference.astype(np.float64) ** 2))),
        "max_absolute_codes": int(magnitude.max()),
        "p99_absolute_codes": float(np.percentile(magnitude, 99)),
        "identical_percent": float(100 * np.mean(magnitude == 0)),
        "within_1_code_percent": float(100 * np.mean(magnitude <= 1)),
        "within_4_codes_percent": float(100 * np.mean(magnitude <= 4)),
        "over_16_codes_percent": float(100 * np.mean(magnitude > 16)),
    }


def compare(directory):
    directory = Path(directory)
    info = json.loads((directory / "pair.json").read_text())
    if (info["width"], info["height"]) != (W, H) or not info["same_decoded_input"]:
        raise ValueError("Not a full-raster same-input pair")
    release = load_kodi(directory / "release.rgba")
    direct = load_kodi(directory / "direct.rgba")
    count = info["metadata_packets"]
    packets_a = metadata_packets(*release, count)
    packets_b = metadata_packets(*direct, count)
    if packets_a != packets_b:
        raise ValueError("Paths produced different output metadata")
    left, right, top, bottom = info["margins_lrtb"]
    if min(left, right, top, bottom) < 0 or left + right >= W or top + bottom >= H:
        raise ValueError("Invalid active-picture margins")
    # Exclude every metadata-bearing row and both pixels of any cropped chroma pair.
    first_row = max(top, (count * 3072 + W - 1) // W)
    first_column = (left + 1) // 2 * 2
    end_column = (W - right) // 2 * 2
    if first_row >= H - bottom or first_column >= end_column:
        raise ValueError("Empty comparison area")
    area = np.s_[first_row:H - bottom, first_column:end_column]
    ia, ca = release[0][area], release[1][area]
    ib, cb = direct[0][area], direct[1][area]
    return {
        "directory": str(directory),
        "capture": info,
        "metadata_identical_and_crc_valid": True,
        "comparison_rectangle_xyxy": [first_column, first_row, end_column, H - bottom],
        "difference_direction": "direct minus release; full-range 12-bit codes",
        "channels": {
            "I": stats(ia, ib),
            "P": stats(ca[:, ::2], cb[:, ::2]),
            "T": stats(ca[:, 1::2], cb[:, 1::2]),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([compare(path) for path in args.directory], indent=2, allow_nan=False))
