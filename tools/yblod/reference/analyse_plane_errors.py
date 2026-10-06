"""CPU-only native-grid comparison. Input paths and raw pixels are never emitted."""
import argparse
import array
import collections
import json
import sys

def load(path):
    result = array.array("H")
    with open(path, "rb") as stream:
        result.frombytes(stream.read())
    if sys.byteorder != "little":
        result.byteswap()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--depth", type=int, default=12)
    args = parser.parse_args()
    a, b = load(args.baseline), load(args.candidate)
    count = args.width * args.height
    if len(a) != len(b) or len(a) != count * 3 // 2:
        raise ValueError("wrong raw plane extent")
    maximum = (1 << args.depth) - 1
    report = []
    start = 0
    for component in range(3):
        width = args.width if component == 0 else args.width // 2
        height = args.height if component == 0 else args.height // 2
        histogram = collections.Counter()
        tiles = [[0] * 16 for _ in range(9)]
        signs = collections.Counter()
        boundary = collections.Counter()
        saturation = collections.Counter()
        changed = 0
        for i in range(width * height):
            baseline, candidate = a[start + i], b[start + i]
            if not (0 <= baseline <= maximum and 0 <= candidate <= maximum):
                raise ValueError("out-of-range output code")
            delta = candidate - baseline
            histogram[delta] += 1
            y, x = divmod(i, width)
            category = "border8" if min(x, y, width - 1 - x, height - 1 - y) < 8 else "interior"
            boundary[category + "_total"] += 1
            if delta:
                changed += 1
                signs["positive" if delta > 0 else "negative"] += 1
                boundary[category + "_changed"] += 1
                tiles[min(y * 9 // height, 8)][min(x * 16 // width, 15)] += 1
                saturation["baseline_endpoint" if baseline in (0, maximum) else "baseline_interior"] += 1
                saturation["candidate_endpoint" if candidate in (0, maximum) else "candidate_interior"] += 1
        report.append(dict(plane=component, count=width * height, changed=changed,
                           signed_histogram=dict(sorted(histogram.items())), signs=dict(signs),
                           boundaries=dict(boundary), changed_saturation=dict(saturation),
                           changed_counts_tiles_16x9=tiles))
        start += width * height
    print(json.dumps(dict(reference="native-integer-not-hardware", planes=report)))

if __name__ == "__main__":
    main()
