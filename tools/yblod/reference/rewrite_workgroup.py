"""Mechanical diagnostic local-size rewrite. Refuse ambiguous input/overwrite."""
import argparse
from pathlib import Path

ORIGINAL = "layout(local_size_x=8,local_size_y=8) in;"


def rewrite(source, x, y):
    if (x, y) not in ((8, 8), (16, 8), (16, 16)):
        raise ValueError("unsupported diagnostic geometry")
    if source.count(ORIGINAL) != 1:
        raise ValueError("expected exactly one canonical local-size declaration")
    return source.replace(ORIGINAL, f"layout(local_size_x={x},local_size_y={y}) in;")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    args = parser.parse_args()
    source = args.source.read_text()
    result = rewrite(source, args.x, args.y)
    with args.output.open("x") as output:
        output.write(result)


if __name__ == "__main__":
    main()
