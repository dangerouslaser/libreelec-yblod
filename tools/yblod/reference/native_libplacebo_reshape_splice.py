#!/usr/bin/env python3
"""Emit isolated hybrid compute shader; never edit canonical source.

Usage: script canonical.comp generated_libplacebo.glsl NEW_OUTPUT.comp
Only BL reshape is replaced. Integer fetch, integer NLQ, final quantization,
dispatch geometry and output format remain the canonical code.
"""
import pathlib
import sys


def splice(canonical: str, fragment: str) -> str:
    begin = "    int64_t total=int64_t(0);\n"
    end = "    int64_t residual=int64_t(0);\n"
    if canonical.count(begin) != 1 or canonical.count(end) != 1:
        raise ValueError("canonical reshape splice markers changed")
    if canonical.count("void main()\n") != 1:
        raise ValueError("canonical entry point changed")
    if "float yb_libplacebo_reshape(uvec3 native_codes, int component)" not in fragment:
        raise ValueError("unexpected generated fragment")
    start = canonical.index(begin)
    stop = canonical.index(end, start)
    original = canonical[start:stop]
    if "int64_t mapped=bound(floor_power_two(total,int(m[5])+4)" not in original:
        raise ValueError("canonical mapped quantization changed")
    replacement = (
        "    // Actual libplacebo reshape; retain native Q16 floor before integer NLQ.\n"
        "    int64_t mapped=int64_t(clamp(floor(\n"
        "        yb_libplacebo_reshape(sample_value.xyz,component)*65536.0),\n"
        "        0.0,65535.0));\n"
    )
    candidate = canonical[:start] + replacement + canonical[stop:]
    return candidate.replace("void main()\n", fragment + "\nvoid main()\n", 1)


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        canonical = pathlib.Path(sys.argv[1]).read_text()
        fragment = pathlib.Path(sys.argv[2]).read_text()
        candidate = splice(canonical, fragment)
        # Refuse overwrite, including the canonical source or generated fragment.
        with pathlib.Path(sys.argv[3]).open("x") as output:
            output.write(candidate)
        return 0
    except (OSError, ValueError) as error:
        print(f"splice failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
