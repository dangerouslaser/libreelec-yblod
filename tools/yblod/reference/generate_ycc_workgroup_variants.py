#!/usr/bin/env python3
"""Create diagnostic-only YCC workgroup variants without changing shader math."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LAYOUT = b"layout(local_size_x=8, local_size_y=8) in;"
GROUPS = ((8, 8), (16, 8), (16, 16))


def variants(source):
    if not 0 < len(source) <= 65536 or b"\0" in source:
        raise ValueError("bounded text shader required")
    if source.count(LAYOUT) != 1 or len(re.findall(rb"layout\s*\(\s*local_size_x", source)) != 1:
        raise ValueError("exact single canonical 8x8 layout required")
    before, after = source.split(LAYOUT)
    return {f"ycc-{x}x{y}.comp": before +
            f"layout(local_size_x={x}, local_size_y={y}) in;".encode() + after
            for x, y in GROUPS}


def generate(shader, output):
    shader, output = Path(shader), Path(output)
    source_state = shader.lstat()
    if not stat.S_ISREG(source_state.st_mode) or not 0 < source_state.st_size <= 65536:
        raise ValueError("bounded regular canonical shader required")
    parent_state = output.parent.stat()
    if not stat.S_ISDIR(parent_state.st_mode) or parent_state.st_uid != os.geteuid():
        raise ValueError("owned output parent required")
    source = shader.read_bytes()
    generated = variants(source)
    output.mkdir(mode=0o700)
    manifest = {"schema": "yblod.ycc-diagnostic-workgroups.v1",
                "scope": "diagnostic-only; production default remains 8x8",
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "only_layout_changed": True, "variants": {}}
    for (name, text), (x, y) in zip(generated.items(), GROUPS):
        with (output / name).open("xb") as stream:
            stream.write(text)
        manifest["variants"][name] = dict(workgroup=[x, y, 1],
                                          sha256=hashlib.sha256(text).hexdigest())
    if (shader.stat().st_ino, shader.stat().st_mtime_ns, shader.stat().st_size) != (
            source_state.st_ino, source_state.st_mtime_ns, source_state.st_size):
        raise ValueError("canonical shader changed during generation")
    if hashlib.sha256(shader.read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise ValueError("canonical shader content changed")
    with (output / "manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shader", type=Path)
    parser.add_argument("fresh_output", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.shader, args.fresh_output), indent=2))
